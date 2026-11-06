"""Independent check of the T03 results page. Imports nothing from the engine, verify_t03.py, analyse.py or report.py.

    python check_page.py [--run headline]        exit 0 = every check passed; non-zero on any failure or if nothing was compared

1. Raw files -> decisions: re-derives every weekly decision (Friday reviews, the latest Master row on or before the date, all three
   BUY) from the three Master files and the published NAV's calendar, and compares state, spell counts and invested weeks with
   decisions.csv and the page.
2. Raw files -> published NAV: the page's published-NAV CAGR and worst fall for each book from Historical Data/parent_nav_*.
3. Page data -> evidence: every number in the page's embedded JSON block (id="page-data") recomputed from the NAV curves in
   daily_nav.csv (CAGR, worst fall of the rule and every comparator), draws.csv (percentiles, p-values, medians, null SDs, MDE,
   shift nulls, R2-R4) and stats.csv (cost paid, trades).
4. Page text -> data: the headline numbers appear on the page as printed (rounded as the page rounds them).
5. The independent verifier's result: verify_t03.json must exist, say it passed, and have compared rows.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
END = pd.Timestamp("2026-08-21")
fails, n = [], 0


def chk(name, ok, detail=""):
    global n
    n += 1
    if not ok:
        fails.append(f"{name}: {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


def cagr(nv):
    return float(nv[-1] ** (252 / (len(nv) - 1)) - 1)


def mdd(nv):
    return float((nv / np.maximum.accumulate(nv) - 1).min())


def pctl(x, d, hb=True):
    tie = np.abs(d - x) <= 1e-12 * max(1.0, abs(x))
    worse = (d < x if hb else d > x) & ~tie
    better = (d > x if hb else d < x) & ~tie
    return (worse.sum() + 0.5 * tie.sum()) / len(d) * 100, (1 + better.sum() + tie.sum()) / (len(d) + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    a = ap.parse_args()
    ev = HERE / "evidence" / a.run
    html = (HERE / "evidence" / "report.html").read_text(encoding="utf-8")
    page = json.loads(re.search(r'<script type="application/json" id="page-data">(.*?)</script>', html, re.S).group(1))
    dec = pd.read_csv(ev / "decisions.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    dr = pd.read_csv(ev / "draws.csv")
    st = pd.read_csv(ev / "stats.csv")

    # 1. raw files -> decisions
    ms = {}
    for nme in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(AA / "Historical Data" / "frozen_2026-09-25" / "Master" / f"Master_{nme}.xlsx", parse_dates=["Date"])
        ms[nme] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    for b in BOOKS:
        raw = pd.read_csv(AA / "Historical Data" / "parent_nav_2026-10-22" / f"{b}.csv")
        cal = pd.DatetimeIndex(sorted(pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")))
        cal = cal[cal <= END]
        wk = pd.Series(cal, index=cal)
        iso = cal.isocalendar()
        last = sorted(wk.groupby([iso.year.values, iso.week.values]).max().values)
        dates = [cal[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > cal[0]]
        st_raw = []
        for d in dates:
            ok = 1
            for s in ms.values():
                ok &= int(s.iloc[s.index.searchsorted(d, side="right") - 1] == "BUY")
            st_raw.append(ok)
        e = dec[dec.book == b]
        chk(f"{b} number of decisions", len(e) == len(dates), f"{len(e)} vs {len(dates)}")
        chk(f"{b} decision dates", list(pd.to_datetime(e.decision_date)) == dates)
        chk(f"{b} states", list(e.state) == st_raw, "state sequences differ")
        runs, cur, c = [], st_raw[0], 0
        for v in st_raw:
            if v == cur:
                c += 1
            else:
                runs.append((cur, c)); cur, c = v, 1
        runs.append((cur, c))
        chk(f"{b} in-spells", sum(1 for v, _ in runs if v == 1) == 9 and sum(1 for v, _ in runs if v == 0) == 9, str(runs))
        # 2. raw published NAV
        raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
        r = raw[(raw.d >= cal[0]) & (raw.d <= END)].sort_values("d")["index"].values
        r = r / r[0]
        chk(f"{b} published CAGR", close(page["books"][b]["pub_cagr"], cagr(r), 1e-9), f"{page['books'][b]['pub_cagr']} vs {cagr(r)}")
        chk(f"{b} published worst fall", close(page["books"][b]["pub_dd"], mdd(r), 1e-9))

    # 3. page data -> evidence
    for b in BOOKS:
        pb = page["books"][b]
        for kind, ck, dk in (("strategy", "cagr", "max_dd"), ("hold_parent", "hold_cagr", "hold_dd"), ("constant_mix", "mix_cagr", "mix_dd"), ("sleeve_only", "sleeve_cagr", "sleeve_dd")):
            v = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == kind)].sort_values("date").nav.values
            chk(f"{b} {kind} NAV starts at 1", close(v[0], 1.0, 1e-12))
            chk(f"{b} {kind} CAGR from NAV", close(pb[ck], cagr(v), 1e-9), f"{pb[ck]} vs {cagr(v)}")
            chk(f"{b} {kind} worst fall from NAV", close(pb[dk], mdd(v), 1e-9))
        sv = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").nav.values
        chk(f"{b} end NAV", close(pb["end_nav"], float(sv[-1]), 1e-9))

        def dd(win="full", cash="lbes", cost=20.8, typ="N4.9"):
            return dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)]
        n49 = dd()
        sh = dd(typ="shift")
        chk(f"{b} draws count", len(n49) == pb["draws"] == 2000, str(len(n49)))
        p1, q1 = pctl(close_val := cagr(sv), n49.cagr.values)
        p2, q2 = pctl(mdd(sv), n49.max_dd.values)
        chk(f"{b} CAGR percentile", close(pb["pct_cagr"], p1, 1e-9) and close(pb["p_cagr"], q1, 1e-9))
        chk(f"{b} drawdown percentile", close(pb["pct_dd"], p2, 1e-9) and close(pb["p_dd"], q2, 1e-9))
        chk(f"{b} null medians", close(pb["null_median_cagr"], float(n49.cagr.median())) and close(pb["null_median_dd"], float(n49.max_dd.median())))
        chk(f"{b} null SD and MDE", close(pb["null_sd_cagr"], float(n49.cagr.std())) and close(pb["mde_cagr_pp"], 280 * float(n49.cagr.std()))
            and close(pb["mde_dd_pp"], 280 * float(n49.max_dd.std())))
        chk(f"{b} shift percentiles", close(pb["shift_pct_cagr"], pctl(cagr(sv), sh.cagr.values)[0]) and close(pb["shift_pct_dd"], pctl(mdd(sv), sh.max_dd.values)[0]))
        for c in (0.0, 50.0):
            vv = nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == "strategy")].sort_values("date").nav.values
            chk(f"{b} C1 percentile at {c}", close(pb[f"pct_cagr_{c:g}"], pctl(cagr(vv), dd(cost=c).cagr.values)[0], 1e-9))
        s_live = st[(st.book == b) & (st.window == "live") & (st.kind == "strategy")].iloc[0]
        chk(f"{b} live percentile", close(pb["live_pct"], pctl(s_live.cagr, dd(win="live").cagr.values)[0], 1e-9) and close(pb["live_cagr"], float(s_live.cagr)))
        s_liq = st[(st.book == b) & (st.cash == "liquidcase") & (st.kind == "strategy")].iloc[0]
        chk(f"{b} LIQUIDCASE percentile", close(pb["liq_pct"], pctl(s_liq.cagr, dd(cash="liquidcase").cagr.values)[0], 1e-9))
        # null holds its table, from the draws file itself
        s_row = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == "strategy")].iloc[0]
        chk(f"{b} every draw: invested weeks equal", bool((n49.invested_weeks == s_row.invested_weeks).all()))
        chk(f"{b} every draw: 9 in and 9 out spells", bool(((n49.n_in_spells == 9) & (n49.n_out_spells == 9)).all()))
        chk(f"{b} every draw: same spell signature", bool((n49.spell_sig == n49.strategy_sig).all()))
        chk(f"{b} cost paid and trades", close(pb["cost_paid"], float(s_row.cost_paid)) and pb["trades"] == int(s_row.trades))
    c1 = sum(page["books"][b]["pct_cagr"] >= 90 for b in BOOKS)
    c2 = sum(page["books"][b]["pct_dd"] >= 90 for b in BOOKS)
    chk("C1 count", page["verdict"]["C1"] == c1)
    chk("C2 count", page["verdict"]["C2"] == c2)
    chk("R4 count", page["verdict"]["R4_live_ge90"] == sum(page["books"][b]["live_pct"] >= 90 for b in BOOKS))

    # 4. page text carries the numbers as printed
    for b in BOOKS:
        pb = page["books"][b]
        for txt in (f"{pb['pct_cagr']:.1f}", f"{pb['pct_dd']:.1f}", f"{100 * pb['cagr']:.1f}%", f"{100 * pb['max_dd']:.1f}%", f"{pb['p_cagr']:.3f}", f"{pb['live_pct']:.1f}"):
            chk(f"{b} page prints {txt}", txt in html)
    chk("page names the pre-registration hash", page["prereg_sha256"][:12] in html)
    chk("page hash equals T03.md header", page["prereg_sha256"] in (HERE / "T03.md").read_text(encoding="utf-8"))
    ex = page["example"]
    chk("worked example ranking adds up", ex["rank_worse"] + ex["rank_tied"] + ex["rank_better"] == 2000)
    chk("worked example percentile", close(ex["pct"], (ex["rank_worse"] + 0.5 * ex["rank_tied"]) / 2000 * 100) and close(ex["p"], (1 + ex["rank_better"] + ex["rank_tied"]) / 2001))
    chk("worked example cost = traded x 20.8/2/10000", close(ex["cost"], ex["traded"] * 20.8 / 2 / 10000, 1e-9))

    # 5. the independent verifier
    vj = ev / "verify_t03.json"
    chk("verify_t03.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0, "verify_t03.json does not say passed")
        chk("verifier compared rows", v.get("gate_compared", 0) > 100000, str(v.get("gate_compared")))
        chk("verifier caught the corrupted copy", bool(v.get("selftest", {}).get("detected")))

    # 6. the regime chart's hover data (id="regime-data") against the evidence, with its own derivation of each session's state
    hv = json.loads(re.search(r'<script type="application/json" id="regime-data">(.*?)</script>', html, re.S).group(1))
    bd = page["best_draw"]
    bk = bd["book"]
    q = lambda kind, c: nav[(nav.book == bk) & (nav.cost_bps == c) & (nav.run == kind)].reset_index(drop=True)
    rq, pq = q("strategy", 20.8), q("hold_parent", 0.0)
    curve = np.load(ev / "draw_curves_20.8.npz")[f"{bk}|N4.9_{bd['draw_id']}"].astype(float)
    nses = len(rq)
    chk("hover: one entry per session", all(len(hv[k]) == nses for k in ("dates", "rule", "draw", "parent", "rs", "ds", "tip")))
    chk("hover: dates are the NAV calendar", hv["dates"] == [d.strftime("%Y-%m-%d (%a)") for d in rq.date])
    chk("hover: rule NAV", np.abs(np.array(hv["rule"]) - rq.nav.values).max() < 6e-5)
    chk("hover: parent NAV (hold, 0 bps)", np.abs(np.array(hv["parent"]) - pq.nav.values).max() < 6e-5)
    chk("hover: draw NAV is the stored curve of the page's draw", np.abs(np.array(hv["draw"]) - curve).max() < 6e-5)
    bs = pd.read_csv(ev / f"draw_{bd['draw_id']}_states.csv")
    dcb = dec[dec.book == bk].reset_index(drop=True)
    chk("hover: draw states file has the book's decisions", len(bs) == len(dcb) and (bs.real_state.values == dcb.state.values).all())
    first = np.array([0] + [nses - 1 if pd.isna(t) else int(rq.index[rq.date == pd.Timestamp(t)][0]) for t in dcb.trade_date.iloc[1:]])
    exp_r, exp_d = np.zeros(nses, int), np.zeros(nses, int)
    for j in range(len(bs)):
        end = first[j + 1] if j + 1 < len(bs) else nses - 1
        exp_r[first[j]:end], exp_d[first[j]:end] = bs.real_state.values[j], bs.draw_state.values[j]
    exp_r[-1], exp_d[-1] = exp_r[-2], exp_d[-2]
    chk("hover: the rule's state each session", (np.array(hv["rs"]) == exp_r).all())
    chk("hover: the draw's state each session", (np.array(hv["ds"]) == exp_d).all())
    chk("hover: every session points at a stretch text", all(0 <= i < len(hv["tips"]) for i in hv["tip"]) and all(isinstance(t, str) and t for t in hv["tips"]))
    # 6b. the per-book growth-of-1 charts' hover data (id="lines-data"): every plotted session and value, against the NAV file
    lh = json.loads(re.search(r'<script type="application/json" id="lines-data">(.*?)</script>', html, re.S).group(1))
    chk("line hover: one entry per book", sorted(lh) == sorted(BOOKS))
    chk("line charts: one hover overlay and one tooltip per book", html.count('class="lc-ov"') == len(BOOKS) and html.count('<div class="tip" hidden></div>') == len(BOOKS))
    for b in BOOKS:
        pick = lambda kind, c=20.8: nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == kind)].reset_index(drop=True)
        cur = {"strategy": pick("strategy"), "hold_parent": pick("hold_parent"), "constant_mix": pick("constant_mix"), "sleeve_only": pick("sleeve_only"),
               "published_D17": nav[(nav.book == b) & (nav.run == "published_D17")].reset_index(drop=True)}
        cal = cur["strategy"].date
        sel = np.unique(np.append(np.arange(0, len(cal), 5), len(cal) - 1))  # every 5th session and the last
        h = lh[b]
        chk(f"line hover {b}: series are the five curves, in legend order", [s["k"] for s in h["series"]] == list(cur))
        chk(f"line hover {b}: plotted sessions", h["n"] == len(sel) and len(h["dates"]) == len(sel))
        chk(f"line hover {b}: dates are the NAV calendar", h["dates"] == [cal[i].strftime("%Y-%m-%d (%a)") for i in sel])
        for s in h["series"]:
            chk(f"line hover {b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - cur[s["k"]].nav.values[sel]).max() < 6e-5)
    r_, d_ = bs.real_state.values, bs.draw_state.values
    chk("regime table: weeks by what the two did", (bd["weeks_both_in"], bd["weeks_both_out"], bd["weeks_draw_only"], bd["weeks_rule_only"]) ==
        (int(((r_ == 1) & (d_ == 1)).sum()), int(((r_ == 0) & (d_ == 0)).sum()), int(((r_ == 0) & (d_ == 1)).sum()), int(((r_ == 1) & (d_ == 0)).sum())))
    # what the shuffle holds, derived again from the weekly states and the session-level arrays above
    sp = lambda a: [(int(a[i]), 0) for i in range(len(a)) if i == 0 or a[i] != a[i - 1]]
    lens = lambda a, v: [len(list(g)) for k, g in __import__("itertools").groupby(a) if k == v]
    chk("held: weeks invested equal and as printed", int(r_.sum()) == int(d_.sum()) == bd["weeks_invested_rule"] == bd["weeks_invested_draw"])
    chk("held: spell counts", (len(lens(r_, 1)), len(lens(r_, 0))) == (len(lens(d_, 1)), len(lens(d_, 0))) == (bd["in_spells"], bd["out_spells"]))
    chk("held: in-spell and out-spell lengths are the same multisets", sorted(lens(r_, 1)) == sorted(lens(d_, 1)) and sorted(lens(r_, 0)) == sorted(lens(d_, 0)))
    chk("held: entries and exits", (int(((r_[1:] == 1) & (r_[:-1] == 0)).sum()), int(((r_[1:] == 0) & (r_[:-1] == 1)).sum())) == (int(((d_[1:] == 1) & (d_[:-1] == 0)).sum()), int(((d_[1:] == 0) & (d_[:-1] == 1)).sum())) == (bd["entries"], bd["exits"]))
    chk("held: first state", r_[0] == d_[0])
    chk("sessions invested, rule and draw, as printed", (int(exp_r[:-1].sum()), int(exp_d[:-1].sum()), nses - 1) == (bd["sessions_invested_rule"], bd["sessions_invested_draw"], bd["sessions_span"]))
    chk("regime section: draw is the highest-CAGR random timing of the book", bd["draw_id"] == int(dr[(dr.book == bk) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.9")].sort_values("cagr").iloc[-1].draw_id))

    print(f"check_page: {n} checks, {len(fails)} failures")
    for f in fails[:40]:
        print("FAIL", f)
    sys.exit(0 if (n > 0 and not fails) else 1)


if __name__ == "__main__":
    main()
