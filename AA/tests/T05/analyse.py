# -*- coding: utf-8 -*-
"""Print every table T05.md section 4 uses, from the stored evidence only. Writes analysis.log; exits non-zero if a validity gate failed.

    python tests/T05/analyse.py [--run headline] [--root DIR]            (from AA/)

--root (default: this folder) is where evidence/<run>/ is read and analysis.log is written; it exists so the script can be
exercised on a scratch copy without touching the real T05 files.

T04's weekly results are printed beside T05's. They are COPIED from T04's stored output (analysis_summary.json and the
Robustness table of analysis.log) and never recomputed.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
T04_DIR = AA / "tests" / "T04"
IND = ["I1", "I2", "I3", "I4", "I5"]
NAME = {"I1": "50-day EMA", "I2": "200-day EMA", "I3": "50-day SMA", "I4": "200-day SMA", "I5": "weekly SuperTrend"}
PRIMARY = 20.8
PASS_MARK = 98.0
MIN_REVIEWS = 20          # reportability gate: >= 20 review decisions in SELL with 1 <= k < n
Z = 0.84 + 2.054          # z(0.98) + z(0.80) = 2.894
SALT = 5                  # seed salt: default_rng([5, i, draw_id])
OUT: list = []


def p(s: str = ""):
    OUT.append(s)
    print(s)


def md(df: pd.DataFrame, floatfmt: dict | None = None) -> str:
    floatfmt = floatfmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("" if np.isnan(v) else (floatfmt.get(c, "{:.2f}")).format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def percentile(x, v, higher_better=True):
    x = np.asarray(x, float)
    tol = 1e-12 * max(1.0, abs(v))
    worse = int((x < v - tol).sum()) if higher_better else int((x > v + tol).sum())
    tied = int((np.abs(x - v) <= tol).sum())
    ge = int((x >= v - tol).sum()) if higher_better else int((x <= v + tol).sum())
    return (worse + 0.5 * tied) / len(x) * 100, (1 + ge) / (len(x) + 1)


# ───────────────────────────── evidence loading (defensive about the new columns)
def need(df: pd.DataFrame, cols, name: str):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise SystemExit(f"{name}: missing column(s) {miss}; found {list(df.columns)}")


def _bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "1.0")


def load_decisions(ev: Path) -> pd.DataFrame:
    """decisions.csv; `review` is the new T05 column. trade_session is read as trade_date; regime is derived from state if absent."""
    dec = pd.read_csv(ev / "decisions.csv")
    if "trade_date" not in dec.columns:
        dec = dec.rename(columns={"trade_session": "trade_date"})
    need(dec, ["j", "decision_date", "state", "review"], "decisions.csv")
    dec["review"] = dec["review"].map(_bool)
    if "regime" not in dec.columns:
        dec["regime"] = np.where(dec["state"] == 1, "BUY", "SELL")
    return dec.sort_values("j").reset_index(drop=True)


def review_schedule(dec: pd.DataFrame) -> pd.DataFrame:
    """Independent re-statement of T05.md 5a on the decision series: monthly = last decision of its calendar month;
    forced = SELL and (j = 0 or the previous decision is BUY). `effective` = flagged and SELL. Also carries the SELL spell number."""
    d = dec.copy()
    d["date"] = pd.to_datetime(d["decision_date"])
    ym = d["date"].dt.to_period("M")
    d["is_monthly"] = (ym != ym.shift(-1)).values
    prev_buy = (d["state"].shift(1).fillna(1) == 1).values
    d["is_forced"] = (d["state"] == 0).values & prev_buy
    d["rule_flag"] = d["is_monthly"] | d["is_forced"]
    d["effective"] = d["review"] & (d["state"] == 0)
    d["last_decision"] = d["j"] == d["j"].max()
    spell, cur = [], 0
    for j in range(len(d)):
        if d["state"].iloc[j] == 0 and (j == 0 or d["state"].iloc[j - 1] == 1):
            cur += 1
        spell.append(cur if d["state"].iloc[j] == 0 else 0)
    d["spell"] = spell

    def kind(r):
        if r["is_forced"] and r["is_monthly"]:
            return "monthly + forced"
        if r["is_forced"]:
            return "forced (first SELL decision)" if r["j"] == 0 else "forced (BUY to SELL flip)"
        return "monthly" if r["is_monthly"] else "flag without a rule reason"
    d["kind"] = d.apply(kind, axis=1)
    return d


def load_selections(ev: Path, dec: pd.DataFrame) -> pd.DataFrame:
    """selections.csv, one row per (window, indicator, decision) with n, k, kept, regime, review_j.
    Accepts T04's shape (one row per indicator and decision, `kept` a ';' list) or the per-stock shape of the plan's table
    (stock_col, selected: one row per basket stock; rows are taken to be the basket's stocks). `window` defaults to 'full'."""
    sel = pd.read_csv(ev / "selections.csv")
    if "window" not in sel.columns:
        sel["window"] = "full"
    if "kept" not in sel.columns and {"stock_col", "selected"} <= set(sel.columns):
        sel["selected"] = sel["selected"].map(_bool)
        keys = ["window", "indicator", "j", "decision_date"]
        agg = {"n": ("selected", "size"), "k": ("selected", "sum"), "kept": ("stock_col", lambda s: ";".join(map(str, s)))}
        # kept must list the selected stocks only
        sel["_kept_name"] = np.where(sel["selected"], sel["stock_col"].astype(str), "")
        agg["kept"] = ("_kept_name", lambda s: ";".join(x for x in s if x))
        if "review_j" in sel.columns:
            agg["review_j"] = ("review_j", "first")
        sel = sel.groupby(keys, as_index=False).agg(**agg)
    need(sel, ["indicator", "j", "decision_date", "k"], "selections.csv")
    if "regime" not in sel.columns:
        reg = dict(zip(dec["decision_date"], dec["regime"]))
        sel["regime"] = sel["decision_date"].map(reg)
    if "n" not in sel.columns:
        raise SystemExit("selections.csv: no basket size column `n`")
    if "nontrivial" not in sel.columns:
        sel["nontrivial"] = (sel["k"] >= 1) & (sel["k"] < sel["n"])
    if "review_j" not in sel.columns:
        # fall back on the full window's decisions.csv flags (r(j) = latest flagged j' <= j)
        rj, last = {}, np.nan
        for j, f in zip(dec["j"], dec["review"]):
            last = j if f else last
            rj[j] = last
        sel["review_j"] = sel["j"].map(rj)
        sel.loc[sel["window"] != "full", "review_j"] = np.nan
    sel["is_review"] = sel["review_j"] == sel["j"]
    return sel


def reportability(sel: pd.DataFrame) -> dict:
    """T05.md section 2: NOT REPORTABLE if fewer than 20 REVIEW decisions in SELL with 1 <= k < n. The window's last decision is not
    traded, so it is excluded here (and counted separately in `reviews_incl_last`)."""
    out = {}
    for win in sorted(sel["window"].unique(), key=lambda w: 0 if w == "full" else 1):
        for nm in IND:
            x = sel[(sel["window"] == win) & (sel["indicator"] == nm)]
            if x.empty:
                continue
            last = x["j"].max()
            sell = x[x["regime"] == "SELL"]
            rev_all = sell[sell["is_review"]]
            rev = rev_all[rev_all["j"] < last]
            nt = rev[(rev["k"] >= 1) & (rev["k"] < rev["n"])]
            out[f"{win}|{nm}"] = dict(sell_decisions=int(len(sell)), reviews=int(len(rev)), reviews_incl_last=int(len(rev_all)), nontrivial=int(len(nt)),
                                      k_zero=int((rev["k"] == 0).sum()), k_all=int((rev["k"] >= rev["n"]).sum()),
                                      mean_k=float(rev["k"].mean()), mean_n=float(rev["n"].mean()), mean_k_sell=float(sell["k"].mean()),
                                      reportable=bool(len(nt) >= MIN_REVIEWS))
    return out


# ───────────────────────────── T04's stored results (copied, never recomputed)
def md_table_after(text: str, heading: str) -> pd.DataFrame:
    i = text.index(heading)
    rows, started = [], False
    for ln in text[i:].split("\n")[1:]:
        if ln.startswith("|"):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
            started = True
        elif started:
            break
    return pd.DataFrame(rows[2:], columns=rows[0])


def t04_stored(t04: Path) -> dict:
    """T04's headline percentiles, trade counts and R2 0 bps percentiles, read from its stored output."""
    summ = json.loads((t04 / "evidence" / "headline" / "analysis_summary.json").read_text(encoding="utf-8"))
    log = (t04 / "analysis.log").read_text(encoding="utf-8")
    rob = md_table_after(log, "## Robustness (R1 to R5)")
    rob["ind"] = rob["indicator"].str.split().str[0]
    r2 = {r["ind"]: dict(p0=float(r["R2 0 bps C1 pct"]), p50=float(r["R2 50 bps C1 pct"])) for _, r in rob.iterrows()}
    audit = json.loads((t04 / "evidence" / "headline" / "audit.json").read_text(encoding="utf-8"))
    dec = pd.read_csv(t04 / "evidence" / "headline" / "decisions.csv")
    return {"res": summ["res"], "r5": summ["r5"], "r2": r2, "audit": audit, "dec": dec}


def classify(c1: bool, p0: float) -> str:
    """T05.md section 2 status rule: a C1 pass is 'selection' only if its 0 bps percentile is also >= 98, else 'turnover-driven'."""
    if not c1:
        return "no C1 pass"
    return "selection" if p0 >= PASS_MARK else "turnover-driven"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--t04", default=str(T04_DIR))
    a = ap.parse_args()
    root, t04dir = Path(a.root), Path(a.t04)
    ev = root / "evidence" / a.run
    audit = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    s = pd.read_csv(ev / "stats.csv")
    d = pd.read_csv(ev / "draws.csv")
    dec = load_decisions(ev)
    sel = load_selections(ev, dec)
    nav = pd.read_csv(ev / "daily_nav.csv").rename(columns={"session": "date"})
    nav["date"] = pd.to_datetime(nav["date"])
    trades = pd.read_csv(ev / "trades.csv").rename(columns={"session": "date"})
    ind_csv = pd.read_csv(ev / "indicators.csv")
    sch = review_schedule(dec)
    rv = sch[sch["effective"]]
    n_rev_all = int(len(rv))
    n_rev_traded = int((rv["last_decision"] == False).sum())  # noqa: E712
    n_forced = int(rv["is_forced"].sum())
    n_monthly = int((rv["is_monthly"] & ~rv["is_forced"]).sum())
    n_both = int((rv["is_monthly"] & rv["is_forced"]).sum())
    last_is_review = bool(sch["effective"].iloc[-1])
    n_flag_buy = int((sch["review"] & (sch["state"] == 1)).sum())
    flag_mismatch = int((sch["review"] != sch["rule_flag"]).sum())
    rp = reportability(sel)
    t4 = t04_stored(t04dir)

    p(f"# T05 analysis of evidence/{a.run}")
    p()
    p(f"**Filter reviews in SELL: {n_rev_all}** ({n_rev_traded} traded; the last decision of the window, {sch['decision_date'].iloc[-1]}, is " +
      ("a flagged SELL review that is not traded" if last_is_review else "not a SELL review") +
      f"). Of the {n_rev_all}: {n_monthly} monthly only, {n_forced} forced (a SELL spell's first decision), {n_both} of those also month-end. "
      f"The flag is set on {int(sch['review'].sum())} of {len(sch)} weekly decisions (`review_mask_count` in audit.json: {audit.get('review_mask_count', 'not recorded')}); "
      f"{n_flag_buy} flagged decisions fall in BUY weeks and have no effect. T04 filtered at all {int((dec['state'] == 0).sum())} SELL decisions.")
    first5 = ", ".join(rv["decision_date"].iloc[:5])
    last5 = ", ".join(rv["decision_date"].iloc[-5:])
    p(f"First reviews: {first5}. Last reviews: {last5}.")
    p()
    gates_ok = True

    # ── gates
    p("## Validity gates")
    v1p = ev / "verify_t05.json"
    v1 = json.loads(v1p.read_text(encoding="utf-8")) if v1p.exists() else None
    v2 = audit["v2"]
    v2_ok = v2["label_after_decision"] == 0 and v2["trade_not_after_decision"] == 0 and v2["indicator_bars_after_query_date"] == 0 and v2["decisions_checked"] > 0
    v3 = audit["v3"]
    v4 = audit["v4"]
    v4_ok = v4["overall"] == "PASS" and v4["yearly"] == "PASS"
    v5 = audit["v5"]
    v5_ok = v5["failed"] == 0 and v5["checked"] >= 50
    v1_ok = bool(v1 and v1.get("exit_ok") and all(c.get("compared", 0) > 0 and c.get("failed", 0) == 0 and c.get("missing", 0) == 0 for c in v1["checks"].values()))
    v3_extra = "".join(f"; {k.replace('_', ' ')} {v3[k]}" for k in ("review_flag_mismatch", "review_mismatch", "frozen_mismatch") if k in v3)
    rows = [("V1", "independent check verify_t05.py", "PASS" if v1_ok else ("FAIL" if v1 else "NOT RUN"),
             (f"{sum(c.get('compared', 0) for c in v1['checks'].values()):,} comparisons, {sum(c.get('failed', 0) for c in v1['checks'].values())} failures; corrupted copy detected: {v1.get('selftest', {}).get('detected')}; I5 SuperTrend branch: desk reading" if v1 else "")),
            ("V2", "point in time", "PASS" if v2_ok else "FAIL",
             f"{v2['decisions_checked']} decisions, 0 labels after the decision; {v2.get('trades_checked', '?')} trades, 0 not after their decision; {v2.get('indicator_stock_dates_checked', 0):,} indicator stock-dates, {v2['indicator_bars_after_query_date']} bars after the query date; {v2.get('weekly_candle_recomputed_stock_dates', '?')} weekly-candle recomputations on bars up to the query date"),
            ("V3", "null holds its table", "PASS" if v3["pass"] else "FAIL",
             f"{v3['draws']:,} draws x 2 windows; {v3['decisions_checked']:,} SELL decisions with k mismatches {v3['k_mismatch']}; {v3['buy_events_checked']:,} BUY events with mismatches {v3['buy_mismatch']}{v3_extra}"),
            ("V4", "always-in reproduces the published NAV", "PASS" if v4_ok else "FAIL",
             f"{v4['first']} -> {v4['last']}: CAGR gap {v4['cagr_gap_pp_yr']:+.3f} pp/yr (limit 0.25); worst calendar year {v4['worst_year']} {v4['worst_year_gap_pp']:+.3f} pp (limit 0.5)"),
            ("V5", "indicator reproducibility", "PASS" if v5_ok else "FAIL", f"{v5['checked']} stock-date pairs vs a hand computation, {v5['failed']} failed")]
    gates_ok = all(r[2] == "PASS" for r in rows)
    p(md(pd.DataFrame(rows, columns=["gate", "what", "result", "detail"])))
    p()
    # cross-checks (not gates)
    t04dec = t4["dec"]
    shared = sorted(set(dec["decision_date"]) & set(t04dec["decision_date"]))
    m1 = dict(zip(dec["decision_date"], dec["state"]))
    m4 = dict(zip(t04dec["decision_date"], t04dec["state"]))
    mism_t04 = sum(1 for dte in shared if m1[dte] != m4[dte])
    line = (f"Cross-checks (not gates): regime series equals T04's headline decisions on {len(shared)} shared decision dates with {mism_t04} mismatches "
            f"({len(dec)} decisions here, {len(t04dec)} in T04); the engine's review flag equals the calendar rule (T05.md 5a) on all but {flag_mismatch} of {len(sch)} decisions")
    t3x = audit.get("t03_regime_crosscheck")
    nx = audit.get("t03_nav_crosscheck")
    if t3x:
        line += f"; regime series equals T03's on {t3x['shared_dates']} shared dates with {t3x['mismatches']} mismatches"
    if nx:
        line += (f"; the full-switch comparator reproduces T03's SCMO_0003 strategy NAV (cost 0 / 20.8 / 50) to a maximum relative difference of "
                 f"{max(x['max_rel_diff_to_2026-08-07'] for x in nx):.1e} up to 2026-08-07 (after that T03 accrued cash by a 90-session rate; this run reads the extended LBES)")
    p(line + ".")
    p()

    # ── decisions
    st = dec["state"].values
    spells, cur, c = [], int(st[0]), 0
    for v in st:
        if int(v) == cur:
            c += 1
        else:
            spells.append((cur, c)); cur, c = int(v), 1
    spells.append((cur, c))
    sell_sp = [c for v, c in spells if v == 0]
    dd = audit["decisions"]
    p("## 4.0 The decision series")
    p(f"- Window {dd['t0']} -> {dd['end']}: {dd['sessions']:,} sessions, {dd['n']} weekly decisions (T0 plus the last session of each later ISO week), the last one not traded.")
    p(f"- BUY {dd['buy']} weeks, SELL {dd['sell']} weeks; {sum(1 for v, _ in spells if v == 0)} SELL spells (the independent unit) of {sorted(sell_sp)} decisions, {sum(1 for v, _ in spells if v == 1)} BUY spells.")
    p(f"- Live window starts {dd['live_t0']}: {dd['live_decisions']} decisions.")
    p(f"- Reviews in SELL: {n_rev_all} ({n_monthly} monthly, {n_forced} forced, of which {n_both} also month-end); {n_rev_traded} before the last, untraded decision. The filter is evaluated only on these dates; every other SELL week reuses the stored pass set of the latest review.")
    p()
    sf = sel[(sel["window"] == "full")]
    kt = {}
    for nm in IND:
        x = sf[sf["indicator"] == nm].set_index("j")
        kt[nm] = x["k"]
    nn = sf[sf["indicator"] == "I1"].set_index("j")["n"]
    pick = pd.concat([rv.iloc[:5], rv.iloc[-5:]]).drop_duplicates("j")
    rows = []
    for _, r in pick.iterrows():
        row = {"review #": int(rv.index.get_loc(r.name)) + 1, "decision date": r["decision_date"], "kind": r["kind"], "SELL spell": int(r["spell"]), "n": int(nn.get(r["j"], np.nan)) if r["j"] in nn.index else ""}
        for nm in IND:
            row[f"k {nm}"] = int(kt[nm].get(r["j"])) if r["j"] in kt[nm].index else ""
        rows.append(row)
    p("First and last five reviews in SELL (n = stocks in the basket in force, k = stocks the indicator keeps):")
    p()
    p(md(pd.DataFrame(rows)))
    p()

    # ── reportability
    p("## 4.0b Reportability and selection counts (review decisions in SELL)")
    rows = []
    for win in ("full", "live"):
        for nm in IND:
            r = rp.get(f"{win}|{nm}")
            if r is None:
                continue
            rows.append({"window": win, "indicator": f"{nm} {NAME[nm]}", "SELL decisions": r["sell_decisions"], "reviews in SELL": r["reviews"], "1 <= k < n": r["nontrivial"], "k = 0": r["k_zero"], "k = n": r["k_all"],
                         "mean k": r["mean_k"], "mean n": r["mean_n"], "mean k, all SELL weeks": r["mean_k_sell"], "reportable (>= 20)": "yes" if r["reportable"] else "NO"})
    p(md(pd.DataFrame(rows), {"mean k": "{:.2f}", "mean n": "{:.2f}", "mean k, all SELL weeks": "{:.2f}"}))
    p()
    arp = audit.get("reportability", {})
    diff = [k for k, r in rp.items() if k in arp and "reviews_1_le_k_lt_n_traded_only" in arp[k] and arp[k]["reviews_1_le_k_lt_n_traded_only"] != r["nontrivial"]]
    p("The gate counts review decisions in SELL with 1 <= k < n (T04 counted every SELL decision); the last decision of each window is not traded and is left out of the count "
      f"(counted with it, the 1 <= k < n totals are {', '.join(str(rp[f'full|{nm}']['nontrivial'] + int(rp[f'full|{nm}']['reviews_incl_last'] > rp[f'full|{nm}']['reviews'])) for nm in IND)} for the full window, an upper bound). "
      + ("These counts equal the engine's own `reviews_1_le_k_lt_n_traded_only` in audit.json." if arp and not diff else f"They DIFFER from the engine's audit.json counts for {', '.join(diff)}." if diff else ""))
    nc = audit.get("indicators_not_computable_stock_dates")
    if nc:
        p()
        p("Stock-dates where an indicator could not be computed (valid bar, too little history) and the stock was excluded: " + ", ".join(f"{k} {v}" for k, v in nc.items()) + ".")
    p()

    # ── worked example
    p("## 4.0a The worked example (one SELL review, the weeks after it, one trade, one null draw)")
    try:
        full_sel = sel[(sel["window"] == "full") & (sel["indicator"] == "I1") & (sel["regime"] == "SELL") & sel["is_review"] & (sel["nontrivial"]) & (sel["n"] >= 8)]
        ex = full_sel[pd.to_datetime(full_sel["decision_date"]) >= pd.Timestamp("2022-06-01")].iloc[0]
        j = int(ex["j"])
        dr = dec[dec["j"] == j].iloc[0]
        bk = ex["basket_eff"] if "basket_eff" in ex.index else dr.get("basket", "?")
        signs = ""
        if "sign_Nifty100" in dr.index:
            signs = f" Master SIGN rows: Nifty 100 {dr['sign_Nifty100']} ({dr['label_Nifty100']}), Midcap 100 {dr['sign_MC100']} ({dr['label_MC100']}), Smallcap 100 {dr['sign_SC100']} ({dr['label_SC100']}); not all three BUY, so the regime is SELL."
        p(f"**The review.** Decision j = {j}, {ex['decision_date']} (the last session of its week), a review ({sch.loc[sch['j'] == j, 'kind'].iloc[0]}).{signs}")
        ic = ind_csv[ind_csv["decision_date"] == ex["decision_date"]].copy()
        if "pass_I1" in ic.columns and "ema50" in ic.columns:
            ic["EMA50 test: close > EMA50"] = np.where(ic["pass_I1"], "keep", "drop")
            p(f"The basket in force (effective {bk}) has n = {int(ex['n'])} stocks. Indicator I1 (close > 50-day EMA) on their closes up to {ex['decision_date']}:")
            p()
            p(md(ic[["stock", "weight", "close_used", "ema50", "EMA50 test: close > EMA50"]].rename(columns={"close_used": "close", "weight": "basket weight"}), {"basket weight": "{:.4f}", "close": "{:.2f}", "ema50": "{:.2f}"}))
            kept_w = ic.loc[ic["pass_I1"], "weight"].sum()
            p()
            p(f"k = {int(ex['k'])} kept, with basket weights adding to {kept_w:.4f}; the other {1 - kept_w:.4f} of the book goes to the sleeve, half GOLDBEES and half LBES cash ({(1 - kept_w) / 2:.4f} each).")
        else:
            p(f"The basket in force (effective {bk}) has n = {int(ex['n'])} stocks; the indicator keeps k = {int(ex['k'])}: {str(ex.get('kept', '')).replace(';', ', ')}. (indicators.csv has no per-stock EMA columns in this shape, so the table is not printed.)")
        # the weeks after the review
        nxt_rev = sch[(sch["j"] > j) & sch["review"] & (sch["state"] == 0)]
        endj = int(nxt_rev["j"].iloc[0]) if len(nxt_rev) else int(dec["j"].max()) + 1
        spell_end = dec[(dec["j"] > j) & (dec["state"] == 1)]
        if len(spell_end):
            endj = min(endj, int(spell_end["j"].iloc[0]))
        between = sel[(sel["window"] == "full") & (sel["indicator"] == "I1") & (sel["j"] > j) & (sel["j"] < endj)]
        if len(between):
            same = int((between["kept"] == ex["kept"]).sum()) if "kept" in between.columns else -1
            p(f"**After the review.** The next {len(between)} SELL weeks (decisions {int(between['j'].min())} to {int(between['j'].max())}) are not reviews: the stored pass set of decision {j} is reused, " +
              (f"and the kept list is identical to the review's on {same} of them (the rest differ only by a basket change)." if same >= 0 else "and every selection row names j as its review date." if (between["review_j"] == j).all() else "(review dates differ from this one on some rows).") +
              f" The next review is decision {endj if len(nxt_rev) else 'none before the window ends'}.")
        tr = trades[(trades["indicator"] == "I1") & (trades["cost_bps"] == PRIMARY)]
        nxt = dr["trade_date"]
        t1 = tr[tr["date"] == nxt]
        if len(t1):
            t1 = t1.iloc[0]
            p(f"**The trade** (next session, {nxt}, at each instrument's OHLC4): portfolio value before V = {t1['V']:.6f}; value traded = {t1['traded']:.6f}; cost = traded x 20.8 / 2 / 10,000 = {t1['cost']:.6f}; every target is then scaled by (V - cost) / V = {(t1['V'] - t1['cost']) / t1['V']:.6f}. Kept after the trade: {t1['kept']}. NAV at that day's close {t1['nav_close_after']:.6f}.")
        else:
            p(f"**The trade:** the selection on {ex['decision_date']} left the target unchanged, so no trade was made on {nxt}.")
        nv = nav[(nav["kind"] == "strategy") & (nav["indicator"] == "I1") & (nav["cost_bps"] == PRIMARY)].set_index("date")["nav"]
        yrs = (len(nv) - 1) / 252
        p(f"**The path.** I1 at 20.8 bps: NAV 1.0000 on {nv.index[0].date()} -> {nv.iloc[-1]:.4f} on {nv.index[-1].date()}; {len(nv):,} sessions, years = ({len(nv):,} - 1) / 252 = {yrs:.3f}; CAGR = {nv.iloc[-1]:.4f}^(1/{yrs:.3f}) - 1 = {100 * (nv.iloc[-1] ** (1 / yrs) - 1):.2f}%.")
        wmx = pd.read_csv(AA / "data" / "holdings_matrix" / "SCMO_0003_holding_weight_matrix.csv", index_col=0, nrows=0)
        ncol = len(wmx.columns)
        stocks_all = list(wmx.columns)
        uu = np.random.default_rng([SALT, 1, 0]).random((len(dec), ncol))
        rj = int(ex["review_j"])
        stk = [x for x in (ic["stock"] if "stock" in ic.columns else ic.get("stock_col", pd.Series([], dtype=str)))]
        if stk:
            bset = [stocks_all.index(x) for x in stk]
            pk = [stocks_all[bset[i]] for i in np.argsort(uu[rj, bset], kind="stable")[: int(ex["k"])]]
            dcagr = 100 * d[(d.indicator == 'I1') & (d.window == 'full') & (d.sleeve == '50_50') & (d.cash == 'lbes') & (d.cost_bps == PRIMARY) & (d.draw_id == 0)]['cagr'].iloc[0]
            p(f"**One null draw** (I1, draw_id 0, seed `default_rng([{SALT}, 1, 0])`, u of shape ({len(dec)}, {ncol})): on the same review the draw keeps the k = {int(ex['k'])} stocks of the {int(ex['n'])} with the smallest u in row {rj} (the review's own row, never the current week's): {', '.join(pk)} (the indicator kept {str(ex['kept']).replace(';', ', ')}). "
              f"It keeps those same stocks, those still in the basket, until the next review; everything else is as the strategy. That draw's after-cost CAGR is {dcagr:.2f}%.")
    except KeyError as e:
        p(f"(worked example not printed: evidence column {e} is missing in this shape)")
    p()

    # ── headline
    p("## 4.1 Headline: after cost at 20.8 bps, full window, 50/50 sleeve, LBES cash")
    rows = []
    res = {}
    base = (s["window"] == "full") & (s["sleeve"] == "50_50") & (s["cash"] == "lbes")

    def draws_for(nm, win, sl, cash, cost):
        return d[(d.indicator == nm) & (d.window == win) & (d.sleeve == sl) & (d.cash == cash) & (d.cost_bps == cost)]

    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = draws_for(nm, "full", "50_50", "lbes", PRIMARY)
        r0 = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == 0.0)].iloc[0]
        x0 = draws_for(nm, "full", "50_50", "lbes", 0.0)
        pc, pv = percentile(x["cagr"], r["cagr"])
        pm, pvm = percentile(x["max_dd"], r["max_dd"])
        pc0 = percentile(x0["cagr"], r0["cagr"])[0]
        rep = bool(rp[f"full|{nm}"]["reportable"])
        c1 = bool(rep and pc >= PASS_MARK)
        res[nm] = dict(pc=pc, pm=pm, pc0=pc0, rep=rep, sd_c=x["cagr"].std(), sd_m=x["max_dd"].std(), cagr=r["cagr"], mdd=r["max_dd"], null_c=x["cagr"].mean(), null_m=x["max_dd"].mean(),
                       trades=r["trades"], null_trades=float(x["trades"].mean()), c1=c1, c2=bool(rep and pm >= PASS_MARK), pv_c=pv, pv_m=pvm, cls=classify(c1, pc0))
        rows.append({"indicator": f"{nm} {NAME[nm]}", "CAGR %": 100 * r["cagr"], "null mean %": 100 * x["cagr"].mean(), "null SD pp": 100 * x["cagr"].std(), "C1 percentile": pc, "p": pv,
                     "C1": "PASS" if res[nm]["c1"] else "FAIL", "0 bps percentile": pc0, "max DD %": 100 * r["max_dd"], "null mean DD %": 100 * x["max_dd"].mean(), "C2 percentile": pm, "C2": "PASS" if res[nm]["c2"] else "FAIL",
                     "end NAV": r["end_nav"], "trades": int(r["trades"])})
    p(f"Window {dd['t0']} -> {dd['end']}; {audit['run']['draws']:,} draws per indicator; pass mark percentile >= {PASS_MARK:.0f} (Bonferroni, 5 indicators, alpha 0.10). The 0 bps percentile (R2) is the turnover-free reading.")
    p()
    p(md(pd.DataFrame(rows), {"p": "{:.4f}", "C1 percentile": "{:.1f}", "0 bps percentile": "{:.1f}", "C2 percentile": "{:.1f}", "end NAV": "{:.3f}"}))
    p()

    p("### Secondary statistics (percentile against the same draws; direction: higher is better for Calmar, lower is better for the rest)")
    rows = []
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = draws_for(nm, "full", "50_50", "lbes", PRIMARY)
        row = {"indicator": f"{nm} {NAME[nm]}"}
        for col, hb, lab in (("vol", False, "vol"), ("ulcer", False, "Ulcer"), ("days_below_10pct", False, "days >=10% below peak"), ("longest_underwater", False, "longest under water"), ("calmar", True, "Calmar")):
            row[lab] = f"{r[col]:.3g} (pct {percentile(x[col], r[col], hb)[0]:.1f})"
        rows.append(row)
    p(md(pd.DataFrame(rows)))
    p()

    # ── what the null does not hold: turnover
    p("### What the null does not hold: trades and cost paid, and the 0 bps percentile (20.8 bps unless stated)")
    rows = []
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = draws_for(nm, "full", "50_50", "lbes", PRIMARY)
        rows.append({"indicator": f"{nm} {NAME[nm]}", "strategy trades": int(r["trades"]), "null mean trades": x["trades"].mean(), "null trades / strategy": x["trades"].mean() / r["trades"] if r["trades"] else np.nan,
                     "strategy cost paid (NAV)": r["cost_paid"], "null mean cost paid": x["cost_paid"].mean(),
                     "CAGR gap pp (strategy - null mean)": 100 * (r["cagr"] - x["cagr"].mean()), "C1 pct at 20.8 bps": res[nm]["pc"], "C1 pct at 0 bps": res[nm]["pc0"]})
    p(md(pd.DataFrame(rows), {"null mean trades": "{:.0f}", "null trades / strategy": "{:.2f}", "strategy cost paid (NAV)": "{:.3f}", "null mean cost paid": "{:.3f}", "CAGR gap pp (strategy - null mean)": "{:+.2f}",
                              "C1 pct at 20.8 bps": "{:.1f}", "C1 pct at 0 bps": "{:.1f}"}))
    p()
    p("Both the strategy and the null now change the kept set only at reviews and on basket changes, but a random set at each review is unrelated to the last one while a moving-average filter's passers overlap heavily month to month, so the null can still trade more. The 0 bps percentile is the turnover-free reading: the gap between the two percentile columns is the part of an indicator's after-cost standing that is turnover.")
    p()

    # ── T04 beside T05
    p("### T04 (weekly filter) beside T05 (monthly filter), copied from T04's stored output")
    r04, r2 = t4["res"], t4["r2"]
    rows = []
    for nm in IND:
        c04 = bool(r04[nm]["c1"])
        rows.append({"indicator": f"{nm} {NAME[nm]}", "T04 C1 pct": r04[nm]["pc"], "T05 C1 pct": res[nm]["pc"], "T04 0 bps pct": r2[nm]["p0"], "T05 0 bps pct": res[nm]["pc0"],
                     "T04 C2 pct": r04[nm]["pm"], "T05 C2 pct": res[nm]["pm"],
                     "T04 trades (strategy / null)": f"{int(r04[nm]['trades'])} / {r04[nm]['null_trades']:.0f}", "T05 trades (strategy / null)": f"{int(res[nm]['trades'])} / {res[nm]['null_trades']:.0f}",
                     "T04 CAGR %": 100 * r04[nm]["cagr"], "T05 CAGR %": 100 * res[nm]["cagr"], "T04 status": classify(c04, r2[nm]["p0"]), "T05 status": res[nm]["cls"]})
    p(md(pd.DataFrame(rows), {c: "{:.1f}" for c in ("T04 C1 pct", "T05 C1 pct", "T04 0 bps pct", "T05 0 bps pct", "T04 C2 pct", "T05 C2 pct")}))
    p()
    t04a = t4["audit"]["decisions"]
    p(f"Filter evaluations: T04 filtered at all {t04a['sell']} SELL decisions of {t04a['n']}; T05 filters at {n_rev_all} reviews ({n_rev_traded} traded) of the same {len(dec)} decisions. "
      f"T04's percentiles are those printed in its section 4.1 and Robustness table (the 0 bps column is its R2); T04's status column applies T05's status rule to those printed numbers. T04's best-of-sweep R5 was percentile {t4['r5']['pct']:.1f}. "
      "The two cadences are judged each against its own null; they are shown side by side, not tested against each other.")
    p()

    # ── comparators
    p("## 4.2 Comparators (benchmarks, not nulls), full window")
    rows = []
    for kind, lab in (("hold_parent", "hold the parent"), ("full_aa_switch", "full AA switch (100% sleeve in SELL; T03's rule)")):
        for cost in (0.0, PRIMARY, 50.0):
            r = s[(s.kind == kind) & (s.cost_bps == cost)].iloc[0]
            rows.append({"run": lab, "cost bps": cost, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    for nm in IND:
        for cost in (PRIMARY,):
            r = s[(s.kind == "constant_mix") & (s.indicator == nm) & (s.cost_bps == cost)].iloc[0]
            rows.append({"run": f"constant mix at {nm}'s equity share f = {r['mean_equity_share']:.3f}", "cost bps": cost, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        rows.append({"run": f"strategy {nm} {NAME[nm]}", "cost bps": PRIMARY, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    p(md(pd.DataFrame(rows), {"Calmar": "{:.2f}", "end NAV": "{:.3f}"}))
    p()
    pub = nav[nav["kind"] == "published_SCMO_0003"].set_index("date")["nav"]
    pub42 = nav[nav["kind"] == "published_SCMO_0042"].set_index("date")["nav"]
    yp = (pub.index[-1] - pub.index[0]).days / 365.25
    y42 = (pub42.index[-1] - pub42.index[0]).days / 365.25
    p(f"Published NAV SCMO_0003 (D17, rebased): {pub.index[0].date()} -> {pub.index[-1].date()}, {100 * (pub.iloc[-1] ** (1 / yp) - 1):.2f}% a year (calendar-day years). "
      f"Published SCMO_0042 (production overlay, `indices.csv`, descriptive only): {pub42.index[0].date()} -> {pub42.index[-1].date()}, {100 * (pub42.iloc[-1] ** (1 / y42) - 1):.2f}% a year.")
    p()
    p("### Calendar-year returns at 20.8 bps (strategy NAV, % ; first and last years are part years)")
    series = {"hold parent": nav[(nav.kind == "hold_parent") & (nav.cost_bps == PRIMARY)], "full AA switch": nav[(nav.kind == "full_aa_switch") & (nav.cost_bps == PRIMARY)]}
    for nm in IND:
        series[nm] = nav[(nav.kind == "strategy") & (nav.indicator == nm) & (nav.cost_bps == PRIMARY)]
    ytab = {}
    for k, v in series.items():
        sr = v.set_index("date")["nav"]
        ye = sr.groupby(sr.index.year).last()
        ytab[k] = (ye / ye.shift(1).fillna(1.0) - 1) * 100
    yt = pd.DataFrame(ytab).rename_axis("year").reset_index()
    yt["year"] = yt["year"].astype(int).astype(str)
    p(md(yt, {c: "{:.1f}" for c in yt.columns if c != "year"}))
    p()

    # ── power
    p("## 4.3 Power and the minimum detectable edge (80% power, pass mark 98)")
    rows = [{"indicator": f"{nm} {NAME[nm]}", "SD of null CAGR pp": 100 * res[nm]["sd_c"], "MDE CAGR pp": Z * 100 * res[nm]["sd_c"], "SD of null max DD pp": 100 * res[nm]["sd_m"], "MDE max DD pp": Z * 100 * res[nm]["sd_m"],
             "strategy minus null mean, CAGR pp": 100 * (res[nm]["cagr"] - res[nm]["null_c"])} for nm in IND]
    p(md(pd.DataFrame(rows), {"strategy minus null mean, CAGR pp": "{:+.2f}"}))
    p()
    sd04 = {nm: 100 * r04[nm]["sd_c"] for nm in IND}
    p(f"MDE = (z_0.98 + z_0.80) x SD = 2.894 x SD of the null. With {sum(1 for v, _ in spells if v == 0)} SELL spells (and {n_rev_all} reviews) the effective sample is small, and the MDE is the edge the test could have seen at 80% power. "
      "T04's null SD of CAGR (pp, copied): " + ", ".join(f"{nm} {sd04[nm]:.2f}" for nm in IND) + "; T05's: " + ", ".join(f"{nm} {100 * res[nm]['sd_c']:.2f}" for nm in IND) + " (fewer re-draws were expected to widen it).")
    p()

    # ── verdict
    p("## 4.4 Verdict against each pre-registered criterion")
    rows = [{"indicator": f"{nm} {NAME[nm]}", "reportable": "yes" if res[nm]["rep"] else "NO", "C1 CAGR pct": res[nm]["pc"], "C1": "PASS" if res[nm]["c1"] else "FAIL",
             "C2 max-DD pct": res[nm]["pm"], "C2": "PASS" if res[nm]["c2"] else "FAIL"} for nm in IND]
    p(md(pd.DataFrame(rows), {"C1 CAGR pct": "{:.1f}", "C2 max-DD pct": "{:.1f}"}))
    p()
    c1p = [nm for nm in IND if res[nm]["c1"]]
    c2p = [nm for nm in IND if res[nm]["c2"]]
    both = [nm for nm in IND if res[nm]["c1"] and res[nm]["c2"]]
    p(f"- Passing C1 (selection): {', '.join(c1p) if c1p else 'none'}. Passing C2 (protection): {', '.join(c2p) if c2p else 'none'}. Passing both: {', '.join(both) if both else 'none'}.")
    fa = s[(s.kind == "full_aa_switch") & (s.cost_bps == PRIMARY)].iloc[0]
    best = max(IND, key=lambda n: res[n]["cagr"])
    p(f"- Best indicator by after-cost CAGR: {best} {NAME[best]} at {100 * res[best]['cagr']:.2f}% against the full AA switch's {100 * fa['cagr']:.2f}% and holding the parent's {100 * s[(s.kind == 'hold_parent') & (s.cost_bps == PRIMARY)].iloc[0]['cagr']:.2f}%.")
    p()
    p("### Status rule for the turnover confound (T05.md section 2, F-AA-M03)")
    rows = [{"indicator": f"{nm} {NAME[nm]}", "C1 pct at 20.8 bps": res[nm]["pc"], "C1": "PASS" if res[nm]["c1"] else "FAIL", "0 bps percentile": res[nm]["pc0"],
             "0 bps >= 98": "yes" if res[nm]["pc0"] >= PASS_MARK else "no", "status of the C1 result": res[nm]["cls"]} for nm in IND]
    p(md(pd.DataFrame(rows), {"C1 pct at 20.8 bps": "{:.1f}", "0 bps percentile": "{:.1f}"}))
    p()
    sel_ok = [nm for nm in IND if res[nm]["cls"] == "selection"]
    to_ok = [nm for nm in IND if res[nm]["cls"] == "turnover-driven"]
    p(f"- A C1 pass is classed *selection* only if its 0 bps percentile is also >= 98, else *turnover-driven*. Selection: {', '.join(sel_ok) if sel_ok else 'none'}. Turnover-driven: {', '.join(to_ok) if to_ok else 'none'}. (A classification of a pass, not a new pass criterion.)")
    p()

    # ── robustness
    p("## Robustness (R1 to R5)")
    rows = []

    def row_for(nm, win, sl, cash, cost):
        r = s[(s.kind == "strategy") & (s.indicator == nm) & (s.window == win) & (s.sleeve == sl) & (s.cash == cash) & (s.cost_bps == cost)].iloc[0]
        x = draws_for(nm, win, sl, cash, cost)
        return r, x, percentile(x["cagr"], r["cagr"])[0], percentile(x["max_dd"], r["max_dd"])[0]
    for nm in IND:
        row = {"indicator": f"{nm} {NAME[nm]}"}
        for lab, win, sl, cash, cost in (("R2 0 bps", "full", "50_50", "lbes", 0.0), ("R2 50 bps", "full", "50_50", "lbes", 50.0), ("R3 LIQUIDCASE", "full", "50_50", "liquidcase", PRIMARY)):
            r, x, pc, pm = row_for(nm, win, sl, cash, cost)
            row[f"{lab} C1 pct"] = pc
        r, x, pc, pm = row_for(nm, "full", "gold100", "lbes", PRIMARY)
        row["R1 C1 pct"], row["R1 C2 pct"] = pc, pm
        rl = rp[f"live|{nm}"]["reportable"]
        r, x, pc, pm = row_for(nm, "live", "50_50", "lbes", PRIMARY)
        row["R4 live CAGR %"] = 100 * r["cagr"]
        row["R4 C1 pct"] = pc if rl else float("nan")
        row["R4 C2 pct"] = pm if rl else float("nan")
        rows.append(row)
    rb = pd.DataFrame(rows)
    p(md(rb, {c: "{:.1f}" for c in rb.columns if c != "indicator"}))
    p()
    p("R1 uses a 100% GOLDBEES sleeve (own null); R2 changes the cost; R3 swaps LBES for LIQUIDCASE from 2024-01-24; R4 is the live window 2021-11 onward with its own review flags, k counts and its own null (reportability on its own reviews). Percentiles at or above 98 are marked in section 4.4's logic; here every column is just the percentile.")
    p()
    best_draw = d[(d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)].pivot(index="draw_id", columns="indicator", values="cagr").max(axis=1)
    sb = max(res[n]["cagr"] for n in IND)
    pc5, pv5 = percentile(best_draw.values, sb)
    p(f"**R5 best-of-sweep null.** The best of the five indicators ({best} {NAME[best]}, after-cost CAGR {100 * sb:.2f}%) is ranked against the best of five random indicators per draw id: percentile {pc5:.1f}, p = {pv5:.4f} (pass mark {PASS_MARK:.0f}); the null's best-of-five averages {100 * best_draw.mean():.2f}% (SD {100 * best_draw.std():.2f} pp). R5: **{'PASS' if pc5 >= PASS_MARK else 'FAIL'}**. (T04's R5 percentile: {t4['r5']['pct']:.1f}.)")
    p()
    if audit.get("readings"):
        p("READINGS (engine): " + "; ".join(f"{k}: {v}" for k, v in audit["readings"].items()))
        p()
    gl = audit.get("goldbees_fills_not_despiked")
    if gl:
        p("GOLDBEES trade sessions after the MCX file's end (2026-09-28), fill = raw OHLC4: " + "; ".join(f"{g['date']} {g['fill_over_close_pct']:+.2f}% from close" for g in gl) + ".")
        p()
    run = audit["run"]
    p(f"Run: {run['name']}, {run['draws']} draws per indicator, {run['seconds']} s, seed {run.get('seed', '?')}; pre-registration sha256 {audit['prereg_sha256']}.")
    (root / "analysis.log").write_text("\n".join(OUT) + "\n", encoding="utf-8")
    summary = {"res": {k: {kk: (bool(vv) if isinstance(vv, (bool, np.bool_)) else vv if isinstance(vv, str) else float(vv)) for kk, vv in v.items()} for k, v in res.items()},
               "r5": {"pct": pc5, "p": pv5, "best": best}, "gates_ok": bool(gates_ok),
               "reviews": {"n_all": n_rev_all, "n_traded": n_rev_traded, "monthly": n_monthly, "forced": n_forced, "both": n_both, "flag_total": int(sch["review"].sum()),
                           "flag_in_buy": n_flag_buy, "flag_vs_rule_mismatch": flag_mismatch},
               "rep": {k: {kk: (bool(vv) if isinstance(vv, bool) else vv) for kk, vv in v.items()} for k, v in rp.items()}}
    json.dump(summary, open(ev / "analysis_summary.json", "w"), indent=1, default=float)
    if not gates_ok:
        print("A VALIDITY GATE DID NOT PASS: nothing above may be read.")
        sys.exit(1)


if __name__ == "__main__":
    main()
