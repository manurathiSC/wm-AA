"""T03 analysis: reads only the shipped evidence in evidence/<run>/ and prints section 4 of the write-up.

    python analyse.py [--run headline]        prints to stdout and writes tests/T03/analysis.log

Imports nothing from the engine. Percentile = (worse + 0.5 * ties) / draws * 100; p-value = (1 + at least as good) / (draws + 1);
ties are equal within a relative 1e-12 (T03.md section 2). Pass criteria are the ones frozen in T03.md section 2.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
PRIMARY = 20.8
PASS_PCT = 90.0
SHIFT_PCT = 75.0
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
out = io.StringIO()


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    out.write(s + "\n")


def table(df: pd.DataFrame, fmt: dict | None = None):
    fmt = fmt or {}
    d = df.copy()
    for c, f in fmt.items():
        if c in d:
            d[c] = d[c].map(lambda v: "" if (isinstance(v, float) and math.isnan(v)) else f(v))
    P(d.to_string(index=False))


def rank(x: float, draws: np.ndarray, higher_better: bool) -> dict:
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    better_draws = (draws > x) & ~tie if higher_better else (draws < x) & ~tie
    worse = (draws < x) & ~tie if higher_better else (draws > x) & ~tie
    n = len(draws)
    return {"worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better_draws.sum()), "draws": n,
            "percentile": (worse.sum() + 0.5 * tie.sum()) / n * 100, "p": (1 + better_draws.sum() + tie.sum()) / (n + 1)}


def stats_from_nav(nav: np.ndarray) -> dict:
    T = len(nav)
    yrs = (T - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"cagr": nav[-1] ** (1 / yrs) - 1, "max_dd": dd.min()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    a = ap.parse_args()
    ev = HERE / "evidence" / a.run
    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    g4 = pd.read_csv(ev / "g_engine.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    exs = pd.read_csv(ev / "draw_states_example.csv")
    vj = ev / "verify_t03.json"
    v5 = ev / "v5_regression.json"
    t03 = (HERE / "T03.md").read_text(encoding="utf-8")
    region = t03[t03.index("\n## 1. Idea and references") + 1:t03.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    h = hashlib.sha256(region.encode("utf-8")).hexdigest()

    P("T03 analysis. Run:", a.run, " engine seconds:", au["run"]["seconds"], " draws per book and cost:", au["run"]["draws"])
    P("Pre-registration sha256 in the header:", au["prereg_sha256"][:16], "| recomputed now:", h[:16], "| match:", au["prereg_sha256"] == h)
    P("Evidence read:", ", ".join(sorted(p.name for p in ev.iterdir())))

    # ── 4.0b gates ────────────────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.0b  GATES\n" + "=" * 100)
    gates = {}
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        ok = bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0 and v.get("gate_compared", 0) > 0
        P("V1 independent check (verify_t03.py): ", "PASS" if ok else "FAIL", f"| gate comparisons {v.get('gate_compared'):,}, failures and missing {v.get('gate_failures_and_missing')}, "
          f"corrupted copy detected: {v.get('selftest', {}).get('detected')}, worst relative NAV difference {max(c['worst_rel'] for k_, c in v['checks'].items() if k_ in ('C-nav0', 'C-cost', 'C-comp-hold-sleeve')):.1e}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (evidence/%s/verify_t03.json missing)" % a.run)
        gates["V1"] = False
    viol = sum(b["v2_label_after_decision"] + b["v2_trade_not_after_decision"] for b in au["books"].values())
    cnt = sum(b["v2_decisions_checked"] + b["v2_trades_checked"] for b in au["books"].values())
    P(f"V2 point in time: violations {viol} of {cnt} checks (labels dated after the decision: 0 required; trade not after its decision: 0 required)")
    gates["V2"] = viol == 0 and cnt > 0
    v3 = au["v3"]
    P(f"V3 null holds its table: N4.9 draws {v3['n49_draws']:,}, spell signature mismatches {v3['n49_sig_mismatch']}, invested-weeks mismatches {v3['n49_invested_weeks_mismatch']}; "
      f"circular shifts {v3['shift_draws']:,}, invested-weeks mismatches {v3['shift_invested_weeks_mismatch']}, largest spell-count gap {v3['shift_spell_count_gap_max']} (a rotation can cut one spell at the wrap)")
    gates["V3"] = v3["n49_sig_mismatch"] == 0 and v3["n49_invested_weeks_mismatch"] == 0 and v3["shift_invested_weeks_mismatch"] == 0
    P("V4 always-in at 0 cost vs the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp every calendar year) and vs the Step 1 rebuild:")
    table(g4, {"cagr_gap_pp_yr": lambda x: f"{x:+.3f}", "worst_year_gap_pp": lambda x: f"{x:+.3f}", "max_rel_diff_vs_step1_rebuild": lambda x: f"{x:.1e}"})
    gates["V4"] = bool((g4["overall"] == "PASS").all() and (g4["yearly"] == "PASS").all() and (g4["max_rel_diff_vs_step1_rebuild"] < 1e-6).all())
    if v5.exists():
        j = json.loads(v5.read_text(encoding="utf-8"))
        P("V5 regression: g0_gate.csv identical after rerunning data/parent_rebuild_hm.py:", j.get("identical"))
        gates["V5"] = bool(j.get("identical"))
    else:
        P("V5 regression: NOT RUN")
        gates["V5"] = False
    P("Gates:", {k: ("PASS" if v else "FAIL") for k, v in gates.items()}, "->", "ALL PASS" if all(gates.values()) else "A GATE FAILED: NOTHING BELOW MAY BE READ")
    P("Reportability: round trips per book (need 4):", {b: au["books"][b]["round_trips"] for b in BOOKS}, "| live window:", {b: au["books"][b]["live_window"] for b in BOOKS})
    P("Weeks that use the previous week's Master row (age >= 5 days, T0 excluded):", {b: au["books"][b]["stale_label_weeks(age>=5d, excluding T0)"] for b in BOOKS})
    P("Decisions: weekly, %d (0007: %d); invested weeks %d of %d (%.1f%%); spells: %d in, %d out; cash accrual: %s" % (
        au["books"]["SCMO_0003"]["decisions"], au["books"]["SCMO_0007"]["decisions"], au["books"]["SCMO_0003"]["invested_weeks"],
        au["books"]["SCMO_0003"]["decisions"], 100 * au["books"]["SCMO_0003"]["invested_weeks"] / au["books"]["SCMO_0003"]["decisions"],
        au["books"]["SCMO_0003"]["in_spells"], au["books"]["SCMO_0003"]["out_spells"], au["books"]["SCMO_0003"]["cash"]))

    # ── 4.0a worked example ──────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.0a  THE WORKED EXAMPLE (SCMO_0003, 20.8 bps)\n" + "=" * 100)
    b = "SCMO_0003"
    d = dec[dec.book == b].reset_index(drop=True)
    j1 = int(d.index[(d.state != d.state.shift()) & (d.index > 0)][0])
    r = d.loc[j1]
    P(f"One decision: week {j1}, decision date {r.decision_date}. Latest Master rows: Nifty100 {r.sign_Nifty100} ({r.label_Nifty100}), MC100 {r.sign_MC100} ({r.label_MC100}), "
      f"SC100 {r.sign_SC100} ({r.label_SC100}). All three BUY: {r.all_three_buy} -> target {'parent' if r.state else '50% GOLDBEES / 50% cash'}; previous week's state {int(d.loc[j1 - 1, 'state'])}. Trade session: {r.trade_date}.")
    t = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    tt = t[t.date == r.trade_date].iloc[0]
    P(f"One trade: {tt['kind']} on {tt['date']} at OHLC4: value before {tt.V:.6f}, traded {tt.traded:.6f} (both sides), cost {tt.cost:.6f} = traded x 20.8/2/10,000, NAV at the close after: {tt.nav_close_after:.6f}")
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    P("NAV around the trade (strategy, 20.8 bps):")
    table(nv.loc[k - 2:k + 2, ["date", "nav"]].assign(date=lambda x: x.date.dt.date), {"nav": lambda x: f"{x:.6f}"})
    s20 = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "strategy")].iloc[0]
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s20.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s20.sessions)} sessions -> years {(s20.sessions - 1) / 252:.4f}, CAGR {100 * s20.cagr:.3f}%, max drawdown {100 * s20.max_dd:.2f}%")
    e0 = exs[(exs.book == b) & (exs.draw_id == 0)].head(20)
    P("One null draw (N4.9, draw_id 0; seed numpy default_rng([3, 0])): the first 20 weekly decisions, real and shuffled state (1 = parent, 0 = sleeve):")
    table(e0[["j", "decision_date", "real_state", "draw_state"]])
    d0 = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == PRIMARY) & (dr.draw_type == "N4.9")]
    x0 = d0[d0.draw_id == 0].iloc[0]
    P(f"  that draw: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, invested weeks {int(x0.invested_weeks)} (strategy {int(s20.invested_weeks)}), spells {int(x0.n_in_spells)} in / {int(x0.n_out_spells)} out")
    rk = rank(s20.cagr, d0.cagr.values, True)
    P(f"One ranking (CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
      f"null median {100 * d0.cagr.median():.2f}%, edge {100 * (s20.cagr - d0.cagr.median()):+.2f} pp")

    # ── 4.1 headline ─────────────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.1  HEADLINE: strategy against the N4.9 null (full window 2019 -> 2026-08-21, LBES cash)\n" + "=" * 100)
    rows = []
    for cost in (0.0, PRIMARY, 50.0):
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == cost) & (st.kind == "strategy")].iloc[0]
            dd_ = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == cost)]
            n = dd_[dd_.draw_type == "N4.9"]
            sh = dd_[dd_.draw_type == "shift"]
            rc, rd = rank(s.cagr, n.cagr.values, True), rank(s.max_dd, n.max_dd.values, True)
            sc, sd = rank(s.cagr, sh.cagr.values, True), rank(s.max_dd, sh.max_dd.values, True)
            rows.append({"cost": cost, "book": b, "CAGR%": 100 * s.cagr, "null_med%": 100 * n.cagr.median(), "edge_pp": 100 * (s.cagr - n.cagr.median()),
                         "pct": rc["percentile"], "p": rc["p"], "draws": rc["draws"], "maxDD%": 100 * s.max_dd, "null_med_DD%": 100 * n.max_dd.median(),
                         "DD_pct": rd["percentile"], "DD_p": rd["p"], "shift_pct": sc["percentile"], "shift_DD_pct": sd["percentile"], "shifts": sc["draws"]})
    H = pd.DataFrame(rows)
    table(H, {"CAGR%": lambda x: f"{x:.2f}", "null_med%": lambda x: f"{x:.2f}", "edge_pp": lambda x: f"{x:+.2f}", "pct": lambda x: f"{x:.2f}", "p": lambda x: f"{x:.5f}",
              "maxDD%": lambda x: f"{x:.2f}", "null_med_DD%": lambda x: f"{x:.2f}", "DD_pct": lambda x: f"{x:.2f}", "DD_p": lambda x: f"{x:.5f}", "shift_pct": lambda x: f"{x:.2f}", "shift_DD_pct": lambda x: f"{x:.2f}"})
    P("pct = percentile of the strategy's after-cost CAGR among the N4.9 draws; DD_pct = same for max drawdown (shallower is better); shift_* = against the circular-shift null.")
    P("\nSecondary statistics at 20.8 bps, percentile against the N4.9 draws (each statistic's better direction):")
    sec = []
    for b in BOOKS:
        s = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "strategy")].iloc[0]
        n = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == PRIMARY) & (dr.draw_type == "N4.9")]
        sec.append({"book": b, **{k: rank(s[k], n[k].values, hb)["percentile"] for k, hb in HIGHER_BETTER.items()}})
    table(pd.DataFrame(sec), {k: (lambda x: f"{x:.1f}") for k in HIGHER_BETTER})

    # ── 4.2 comparators ──────────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.2  COMPARATORS (benchmarks, not nulls), same window, T0 = 1.000\n" + "=" * 100)
    comp = []
    for cost in (0.0, PRIMARY, 50.0):
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
                s = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            pn = nav[(nav.book == b) & (nav.run == "published_D17")].nav.values
            ps = stats_from_nav(pn)
            row["published_CAGR%"], row["published_DD%"] = 100 * ps["cagr"], 100 * ps["max_dd"]
            comp.append(row)
    C = pd.DataFrame(comp)
    table(C, {c: (lambda x: f"{x:.2f}") for c in C.columns if c.endswith("%")})
    f = au["books"]["SCMO_0003"]["invested_weeks"] / au["books"]["SCMO_0003"]["decisions"]
    P(f"Constant mix holds {100 * f:.1f}% in the parent (the strategy's average); hold_parent is the engine with the decision fixed IN; published_D17 is the published NAV rebased to 1.000 on the same dates.")

    # ── 4.3 MDE ──────────────────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.3  POWER: round trips and the minimum detectable edge (MDE = 2.8 x null SD; 80% power, two-sided 5%)\n" + "=" * 100)
    mde = []
    for b in BOOKS:
        n = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == PRIMARY) & (dr.draw_type == "N4.9")]
        sh = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == PRIMARY) & (dr.draw_type == "shift")]
        mde.append({"book": b, "round_trips": au["books"][b]["round_trips"], "null_sd_CAGR_pp": 100 * n.cagr.std(), "MDE_CAGR_pp": 280 * n.cagr.std(),
                    "shift_sd_CAGR_pp(pilot)": 100 * sh.cagr.std(), "null_sd_DD_pp": 100 * n.max_dd.std(), "MDE_DD_pp": 280 * n.max_dd.std(),
                    "shift_sd_DD_pp(pilot)": 100 * sh.max_dd.std()})
    M = pd.DataFrame(mde)
    table(M, {c: (lambda x: f"{x:.2f}") for c in M.columns if c.endswith("pp") or c.endswith("(pilot)")})
    P("T03.md section 3 step 12: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written.")

    # ── 4.4 verdict ──────────────────────────────────────────────────────────
    P("\n" + "=" * 100 + "\n4.4  VERDICT against the pre-registered criteria (after cost, 20.8 bps)\n" + "=" * 100)
    hp = H[H.cost == PRIMARY].set_index("book")
    c1n = int((hp.pct >= PASS_PCT).sum())
    c2n = int((hp.DD_pct >= PASS_PCT).sum())
    mdeb = M.set_index("book")
    def mdetxt(col):
        return "; ".join(f"{b}: undetectable below {mdeb.loc[b, col]:.1f} pp" for b in BOOKS)
    c1list = ", ".join("%s %.1f" % (b[-4:], hp.loc[b, "pct"]) for b in BOOKS)
    c2list = ", ".join("%s %.1f" % (b[-4:], hp.loc[b, "DD_pct"]) for b in BOOKS)
    V = [("C1 timing (H1)", f"CAGR percentile >= {PASS_PCT:.0f} in >= 3 of 4 books: {c1n} of 4 ({c1list})", c1n >= 3,
          "" if c1n >= 3 else mdetxt("MDE_CAGR_pp")),
         ("C2 protection (H2)", f"max-drawdown percentile >= {PASS_PCT:.0f} in >= 3 of 4 books: {c2n} of 4 ({c2list})", c2n >= 3,
          "" if c2n >= 3 else mdetxt("MDE_DD_pp"))]
    for name, res, ok, m in V:
        P(f"{name:22s} {'PASS' if ok else 'FAIL'}   {res}   {('MDE: ' + m) if m else ''}")
    P("\nRobustness (decide a finding's status, not the verdicts):")
    r1c = int((hp.shift_pct >= SHIFT_PCT).sum())
    r1d = int((hp.shift_DD_pct >= SHIFT_PCT).sum())
    P(f"R1 circular-shift null, percentile >= {SHIFT_PCT:.0f} in >= 3 of 4: CAGR {r1c} of 4 -> {'PASS' if r1c >= 3 else 'FAIL'}; max drawdown {r1d} of 4 -> {'PASS' if r1d >= 3 else 'FAIL'}")
    for cost in (0.0, 50.0):
        hc = H[H.cost == cost]
        n_ = int((hc.pct >= PASS_PCT).sum())
        lst = ", ".join("%s %.1f" % (bb[-4:], x) for bb, x in zip(hc.book, hc.pct))
        P(f"R2 C1 at {cost} bps: {n_} of 4 books >= {PASS_PCT:.0f} -> {'PASS' if n_ >= 3 else 'FAIL'}  ({lst})")
    rr = {}
    for label, win, cash in (("R3 LIQUIDCASE cash", "full", "liquidcase"), ("R4 live window 2021-11 -> 2026-08", "live", "lbes")):
        pcts = []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == PRIMARY) & (st.kind == "strategy")]
            n = dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == PRIMARY) & (dr.draw_type == "N4.9")]
            if len(s) and len(n):
                pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
        n_ = sum(x >= PASS_PCT for x in pcts)
        P(f"{label}: C1 percentiles {[round(x, 1) for x in pcts]} -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if (n_ >= 3) else 'FAIL'}")
    P("\nOutcome map (T03.md section 2): C1", "PASS" if c1n >= 3 else "FAIL", "/ C2", "PASS" if c2n >= 3 else "FAIL")
    P("Hypotheses: H1 (timing)", "SUPPORTED in-sample (PROVISIONAL: nothing is unseen)" if c1n >= 3 else "FALSIFIED", "| H2 (protection)", "SUPPORTED in-sample (PROVISIONAL)" if c2n >= 3 else "FALSIFIED")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    (HERE / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    sys.exit(0 if all(gates.values()) else 1)


if __name__ == "__main__":
    main()
