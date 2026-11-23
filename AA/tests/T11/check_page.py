"""Independent check of the T11 results page. Imports nothing from the engine, verify_t11.py, analyse.py or report.py, and opens nothing but the evidence directory (and, for the
historical reference, T06's, T08's and T09's stored evidence, and the text of data/APPROVED_DATA.md and T11.md).

    python tests/T11/check_page.py [--run headline]                     exit 0 = every check passed; non-zero on any failure or if nothing was compared
    python tests/T11/check_page.py --evidence DIR [--out DIR] [--expect-draws N] [--books SCMO_0003] [--regen N]

1. Evidence -> decisions: re-derives every weekly decision date and trade date (T0, then the last session of each ISO week, on the NAV calendar of daily_nav.csv) and every state, gold
   state and sleeve weight (all three index signs BUY; the MAUc1 sign) from the signs recorded in decisions.csv, and compares them with decisions.csv, gold_signal.csv, real_states.npz
   (full window, and the R3 window sliced from the full series) and the page; the Master labels are not after their decision, the Smallcap 100 labels not before 2011-11-25.
2. The NAV files: the rebuilt parent NAV (parent_nav_*.csv) equals the hold_parent (0 and 20.8 bps), strategy_fixed50 and strategy runs of daily_nav.csv, its sidecar .md carries the
   pre-registered caption, and every chart of those NAVs on the page carries it; baskets.csv against the calendar.
3. Inputs: every input the page lists is an APPROVED row of data/APPROVED_DATA.md (this script's own parse: status, through-date, sha256 prefix, usable-from marker), covers the window,
   and the page's 'As of' date is the register's. No file is hashed here (the verifier does that).
4. Page data -> evidence: every number in the page's embedded JSON (id="page-data"): the NAV curves in daily_nav.csv (CAGR, worst fall of every run at three costs), draws.csv
   (percentiles, p-values, Holm p over m = 6, medians, SDs, spreads, MDE, sessions invested, sleeve trades per draw, R1 to R7), stats.csv, r7_flagged_days.csv, r7_export.csv, the
   historical references (T06's, T08's and T09's stored draws, if present), the outcome-map rows and the verdict counts.
5. The samplers, from scratch: the number of allowed tuples (in-or-out and gold, full and R3) by an own DP and by inclusion-exclusion against count_table.json, bounds
   lo = min(2, shortest spell), hi = longest spell of each state derived from the real series; the draw-0 replays of F1 (seed [14, 6, 0]) and F3 (seed [14, 11, 6, 0]) against
   the page's steps and draw_states.npz; the first --regen draws of all four samplers regenerated from their seeds and compared with draw_states.npz; the four books share the draws.
6. Every draw of every null in draw_states.npz: weeks, first state, spell counts, sums, N4.9 and N4.9-g sorted lengths, N4.10 and N4.10-g per-state bounds; draws.csv columns
   (sessions invested, sleeve trades, length strings) recomputed from the states.
7. The worked trades (exit, gold flip, entry, basket change): identities, units (positions.csv), dates; every sleeve-trade and basket-change row of the evidence against the decisions and baskets.csv.
8. Page text carries the headline numbers as printed; the held/randomised tables, the outcome map and the amendments are T11.md's; the power note, the data caveats, the no-hold-out
   disclosure and the parent captions are present; the parent captions of T09 are gone.
9. The verifier's result (verify_t11.json) and the gates in analysis.log.
10. Hover data: regime-data (every session's values, states, MAUc1 and sleeve weight, from draw_states.npz and the NAV files), lines-data (every plotted session of the seven comparator
   curves and of the four rebuilt-NAV curves of each parent), bars-data (every bin of every histogram, spell-length chart and sampler chart, from draws.csv and draw_states.npz, and the
   bar rectangles in the SVG against those arrays).
"""
import argparse
import ast
import base64
import hashlib
import html as H
import itertools
import json
import math
import re
import sys
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
T0, END, R3_FROM = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02"), pd.Timestamp("2015-01-02")   # T11.md section 3
SC_SIGNAL_FROM = pd.Timestamp("2011-11-25")
KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
R7_BASE = ("strategy", "strategy_fixed50", "hold_parent")
R7_VARS = ("flagged", "noexport")
CRIT = [("A1", "cagr", "F1f", "F2f"), ("A2", "max_dd", "F1f", "F2f"), ("C1", "cagr", "F1", "F2"), ("C2", "max_dd", "F1", "F2"), ("C3", "cagr", "F3", "F4"), ("C4", "max_dd", "F3", "F4")]
TAGS = {"F1": ("F1", "timed", "strategy"), "F2": ("F2", "timed", "strategy"), "F3": ("F3", "timed", "strategy"), "F4": ("F4", "timed", "strategy"), "F5": ("F5", "timed", "strategy"),
        "F1f": ("F1", "fixed50", "strategy_fixed50"), "F2f": ("F2", "fixed50", "strategy_fixed50")}
TAG_OF = {"A1": ("F1f", "F2f", "cagr"), "A2": ("F1f", "F2f", "dd"), "C1": ("F1", "F2", "cagr"), "C2": ("F1", "F2", "dd"), "C3": ("F3", "F4", "cagr"), "C4": ("F3", "F4", "dd")}
SEEDS = {"N4.9": (14, 3), "N4.10": (14, 6), "N4.9-g": (14, 11, 3), "N4.10-g": (14, 11, 6)}
PARENT_NAV = "parent_nav_2014-09-01_2019-01-02"
CAPTION = "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02"
RB = {"hold_parent_0bps": ("rb_hold0", "hold_parent", 0.0), "hold_parent_20.8bps": ("rb_hold20", "hold_parent", 20.8), "part_a_20.8bps": ("rb_a", "strategy_fixed50", 20.8), "part_b_20.8bps": ("rb_b", "strategy", 20.8)}
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
    return float((worse.sum() + 0.5 * tie.sum()) / len(d) * 100), float((1 + better.sum() + tie.sum()) / (len(d) + 1)), int(worse.sum()), int(tie.sum()), int(better.sum())


def holm(ps):
    m = len(ps)
    order = np.argsort(ps)
    out, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out


def spells(a):
    return [(k, len(list(g))) for k, g in itertools.groupby(map(int, a))]


def lens(a, v):
    return [m for k, m in spells(a) if k == v]


def ways_ie(k, S, lo, hi):
    t = S - k * lo
    tot = 0
    for j in range(k + 1):
        top = t - j * (hi - lo + 1) + k - 1
        if top >= k - 1:
            tot += (-1) ** j * comb(k, j) * comb(top, k - 1)
    return tot


_DP = {}


def dp(k, S, lo, hi):
    key = (k, S, lo, hi)
    if key not in _DP:
        c = [[0] * (S + 1) for _ in range(k + 1)]
        c[0][0] = 1
        for m in range(1, k + 1):
            for t in range(S + 1):
                c[m][t] = sum(c[m - 1][t - x] for x in range(lo, hi + 1) if t - x >= 0)
        _DP[key] = c
    return _DP[key]


def bounds_of(r):
    return {s: (min(2, min(lens(r, s))), max(lens(r, s))) for s in (1, 0)}


def replay(seed, names, ks, Ss, bnds):
    rg = np.random.default_rng(seed)
    out = {}
    for nm in names:
        k, S = ks[nm], Ss[nm]
        lo, hi = bnds[nm]
        c = dp(k, S, lo, hi)
        t, parts = S, []
        for m in range(k, 0, -1):
            cum = np.cumsum(np.array([c[m - 1][t - x] if t - x >= 0 else 0 for x in range(lo, hi + 1)], dtype=float))
            u = float(rg.random())
            x = lo + min(int(np.searchsorted(cum, u * cum[-1], side="right")), hi - lo)
            parts.append((x, u, int(c[m][t]), int(c[m - 1][t - x])))
            t -= x
        out[nm] = parts
    return out


def interleave(first, pools):
    out, state, ptr = [], first, {1: 0, 0: 0}
    while ptr[1] < len(pools[1]) or ptr[0] < len(pools[0]):
        out += [state] * pools[state][ptr[state]]
        ptr[state] += 1
        state = 1 - state
    return np.array(out, dtype=int)


def regen_free(real, did, seed):
    r = spells(real)
    ks = {1: sum(1 for v, _ in r if v == 1), 0: sum(1 for v, _ in r if v == 0)}
    Ss = {1: sum(c for v, c in r if v == 1), 0: sum(c for v, c in r if v == 0)}
    bn = bounds_of(real)
    rp = replay([*seed, did], (1, 0), ks, Ss, bn)
    return interleave(int(real[0]), {s: [p[0] for p in rp[s]] for s in (1, 0)})


def regen_shuffle(real, did, seed):
    rng = np.random.default_rng([*seed, did])
    r = spells(real)
    ins = [c for v, c in r if v == 1]
    outs = [c for v, c in r if v == 0]
    ins = [ins[i] for i in rng.permutation(len(ins))]
    outs = [outs[i] for i in rng.permutation(len(outs))]
    return interleave(int(real[0]), {1: ins, 0: outs})


def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    asof = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", txt).group(1)
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4], "note": " | ".join(c[5:])})
    return asof, rows


def nice_ticks_max(hi, k=4):
    s = hi / k
    m = 10 ** math.floor(math.log10(s))
    r = s / m
    st = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
    v, last = 0.0, 0.0
    while v <= hi + 1e-9:
        last = v
        v += st
    return last


def derive_dates(c):
    """Decision dates and their trade dates on the session calendar c: T0 = c[0], then the last session of each ISO week after T0; the trade is on the next session (NaT after the last)."""
    iso = c.isocalendar()
    last = sorted(pd.Series(c, index=c).groupby([iso.year.values, iso.week.values]).max().values)
    dates = [c[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > c[0]]
    trade = []
    for d_ in dates:
        k = int(c.get_loc(d_))
        trade.append(c[k + 1] if k + 1 < len(c) else pd.NaT)
    return dates, trade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--expect-draws", type=int, default=2000)
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"))
    ap.add_argument("--t08", default=str(AA / "tests" / "T08" / "evidence" / "headline"))
    ap.add_argument("--t09", default=str(AA / "tests" / "T09" / "evidence" / "headline"))
    ap.add_argument("--doc", default=str(HERE / "T11.md"))
    ap.add_argument("--books", default=None, help="comma list; for evidence directories that hold fewer than the four books")
    ap.add_argument("--regen", type=int, default=300, help="how many draws of each sampler to regenerate from the seeds (0 = none)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B0 = BOOKS[0]
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev
    else:
        logdir, outdir = HERE, ev.parent
    t06, t08, t09 = Path(a.t06), Path(a.t08), Path(a.t09)
    ND = a.expect_draws
    html = (outdir / "report.html").read_text(encoding="utf-8")

    def block(i):
        return json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))

    page, hv, lh, bd = block("page-data"), block("regime-data"), block("lines-data"), block("bars-data")
    text = H.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)))
    dec = pd.read_csv(ev / "decisions.csv")
    gsig = pd.read_csv(ev / "gold_signal.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    dr = pd.read_csv(ev / "draws.csv")
    st = pd.read_csv(ev / "stats.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    po = pd.read_csv(ev / "positions.csv")
    tr = pd.read_csv(ev / "trades.csv")
    bsk = pd.read_csv(ev / "baskets.csv")
    r7f = pd.read_csv(ev / "r7_flagged_days.csv")
    r7x = pd.read_csv(ev / "r7_export.csv")
    pn_first_line = (ev / f"{PARENT_NAV}.csv").read_text(encoding="utf-8").split("\n", 1)[0]
    if pn_first_line.strip() != "book,date,hold_parent_0bps,hold_parent_20.8bps,part_a_20.8bps,part_b_20.8bps":
        print(f"FAIL {PARENT_NAV}.csv: the first line is not the header (a # comment line breaks pandas readers): {pn_first_line[:80]!r}")
        sys.exit(1)
    pnd = pd.read_csv(ev / f"{PARENT_NAV}.csv", parse_dates=["date"])
    pcap = (ev / f"{PARENT_NAV}.md").read_text(encoding="utf-8")
    z = np.load(ev / "draw_states.npz")
    ST = {k: z[k] for k in z.files}
    rz = np.load(ev / "real_states.npz")
    RZ = {k: rz[k] for k in rz.files}
    curves = np.load(ev / "draw_curves_20.8.npz")
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    asof, arows = approved_rows()
    appr = [r for r in arows if r["status"] == "APPROVED"]
    LIQ = "liq" if "liq" in set(st.cash) else "liquidcase"
    docn = Path(a.doc).read_text(encoding="utf-8").replace("\r\n", "\n")

    # 1. the decisions, re-derived from the evidence's own calendar and signs
    cal_all = pd.DatetimeIndex(nav[(nav.book == B0) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").date)
    chk("calendar: 1,070 sessions, T0 2014-09-01 to END 2019-01-02", len(cal_all) == 1070 and cal_all[0] == T0 and cal_all[-1] == END, f"{len(cal_all)} {cal_all[0]} {cal_all[-1]}")
    dates_exp, trade_exp = derive_dates(cal_all)
    cal, rule, gold, rin, rout, gbuy, gsell = {}, {}, {}, {}, {}, {}, {}
    r3_io, r3_g = {}, {}
    chk("decisions: 228 weekly decisions on the calendar, the first on T0", len(dates_exp) == 228 and dates_exp[0] == T0, str(len(dates_exp)))
    for b in BOOKS:
        cal[b] = cal_all
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        sg = [[e.sign_Nifty100[i], e.sign_MC100[i], e.sign_SC100[i]] for i in range(len(e))]
        sr = np.array([int(all(x == "BUY" for x in s_)) for s_ in sg])
        gr = np.array([int(x == "BUY") for x in e.sign_MAUc1])
        rule[b], gold[b] = sr, gr
        rin[b], rout[b], gbuy[b], gsell[b] = lens(sr, 1), lens(sr, 0), lens(gr, 1), lens(gr, 0)
        chk(f"{b} number of decisions", len(e) == len(dates_exp) == page["weeks"][b], f"{len(e)} vs {len(dates_exp)}")
        chk(f"{b} decision dates (T0, then the last session of each ISO week)", list(pd.to_datetime(e.decision_date)) == dates_exp)
        chk(f"{b} decision_idx is the position of the decision date on the calendar", list(e.decision_idx) == [int(cal_all.get_loc(d_)) for d_ in dates_exp])
        chk(f"{b} in-or-out states = all three index signs BUY", list(e.state) == list(sr) and list(e.all_three_buy.astype(bool)) == [bool(x) for x in sr], "state sequences differ")
        chk(f"{b} signs are BUY or SELL", all(x in ("BUY", "SELL") for s_ in sg for x in s_) and set(e.sign_MAUc1) <= {"BUY", "SELL"})
        chk(f"{b} gold states (g) and sleeve weights (gw)", list(e.g) == list(gr) and np.abs(e.gw.values - np.where(gr == 1, 0.8, 0.2)).max() < 1e-12)
        chk(f"{b} trade dates (next session; none after the last decision)", len(e) == len(trade_exp) and all((pd.isna(x) and pd.isna(y)) or (not pd.isna(x) and not pd.isna(y) and pd.Timestamp(x) == pd.Timestamp(y)) for x, y in zip(e.trade_date, trade_exp)))
        labs = [[pd.Timestamp(e[c_][i]) for c_ in ("label_Nifty100", "label_MC100", "label_SC100")] for i in range(len(e))]
        glab = [pd.Timestamp(x) for x in e.label_MAUc1]
        chk(f"{b} no Master label dated after its decision; Smallcap 100 labels not before 2011-11-25", all(max(l) <= d_ for l, d_ in zip(labs, dates_exp)) and all(g_ <= d_ for g_, d_ in zip(glab, dates_exp)) and all(l[2] >= SC_SIGNAL_FROM for l in labs))
        chk(f"{b} latest_label and label_age_days are the latest label and its age", all(pd.Timestamp(e.latest_label[i]) == max(labs[i]) and int(e.label_age_days[i]) == (dates_exp[i] - max(labs[i])).days for i in range(len(e))))
        gg = gsig[gsig.book == b].sort_values("j")
        chk(f"{b} gold_signal.csv equals the decisions' gold series", list(gg.g) == list(gr) and list(pd.to_datetime(gg.decision_date)) == dates_exp and list(gg.sign_MAUc1) == list(e.sign_MAUc1) and np.abs(gg.gw.values - e.gw.values).max() < 1e-12)
        chk(f"{b} real_states.npz (full) equal the decisions' series", (RZ[f"{b}|full|io"].astype(int) == sr).all() and (RZ[f"{b}|full|gold"].astype(int) == gr).all())
        keep = np.array([d_ >= R3_FROM for d_ in dates_exp])
        chk(f"{b} the R3 window starts on a full-window decision date ({R3_FROM.date()})", R3_FROM in dates_exp and page["r3_start"] == str(R3_FROM.date()))
        r3_io[b], r3_g[b] = RZ[f"{b}|r3|io"].astype(int), RZ[f"{b}|r3|gold"].astype(int)
        chk(f"{b} real_states.npz (R3) equal the full series from {R3_FROM.date()} on", (r3_io[b] == sr[keep]).all() and (r3_g[b] == gr[keep]).all(), f"{len(r3_io[b])} vs {int(keep.sum())}")
        chk(f"{b} spells on the page", page["books"][b]["rule_in"] == rin[b] and page["books"][b]["rule_out"] == rout[b] and page["books"][b]["rule_buy"] == gbuy[b] and page["books"][b]["rule_sell"] == gsell[b], f"{rin[b]} {rout[b]}")
        nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date")
        chk(f"{b} NAV calendar is the common one", list(nvs.date) == list(cal_all))
    chk("start and end dates", page["start"] == str(T0.date()) and page["end"] == str(END.date()))
    BNDF = {kind: bounds_of(r) for kind, r in (("io", rule[B0]), ("gold", gold[B0]))}
    chk("the four books have the same in-or-out and gold series", all((rule[b] == rule[B0]).all() and (gold[b] == gold[B0]).all() for b in BOOKS))
    chk("the real series' bounds: in [1, 28], out [2, 34], BUY [2, 36], SELL [2, 19] (T11.md section 2; computed here as lo = min(2, shortest), hi = longest)",
        BNDF["io"][1] == (1, 28) and BNDF["io"][0] == (2, 34) and BNDF["gold"][1] == (2, 36) and BNDF["gold"][0] == (2, 19), str(BNDF))
    chk("the rule starts IN; 8 in-spells and 8 out-spells; gold starts BUY with 10 BUY and 9 SELL spells (T11.md section 2)", rule[B0][0] == 1 and len(rin[B0]) == 8 and len(rout[B0]) == 8 and gold[B0][0] == 1 and len(gbuy[B0]) == 10 and len(gsell[B0]) == 9)

    # 2. the NAV files, baskets
    chk(f"{PARENT_NAV}.csv: the first line is the header (no # comment line) and the columns are the pre-registered ones", pn_first_line.strip() == "book,date,hold_parent_0bps,hold_parent_20.8bps,part_a_20.8bps,part_b_20.8bps", pn_first_line)
    chk(f"{PARENT_NAV}.md carries the pre-registered caption and says the file is not approved data and no other test may read it", CAPTION in pcap and "not entered in data/APPROVED_DATA.md" in pcap and "no other test may read it" in pcap)
    chk("the page's caption is the pre-registered one", page["caption"] == CAPTION)
    for b in BOOKS:
        pq = pnd[pnd.book == b].sort_values("date").reset_index(drop=True)
        chk(f"{b} {PARENT_NAV}.csv: one row per session, on the calendar, base 1.0 at T0", len(pq) == len(cal_all) and list(pq.date) == list(cal_all) and all(abs(float(pq[c_].iloc[0]) - 1.0) < 1e-12 for c_ in RB))
        for col_, (key_, run_, c_) in RB.items():
            ref_ = nav[(nav.book == b) & (nav.cost_bps == c_) & (nav.run == run_)].sort_values("date").nav.values
            chk(f"{b} {PARENT_NAV}.csv {col_} equals the {run_} NAV of daily_nav.csv at {c_:g} bps", len(ref_) == len(pq) and np.abs(pq[col_].values / ref_ - 1).max() < 1e-12)
        bb_ = bsk[bsk.book == b].sort_values("basket_no").reset_index(drop=True)
        chk(f"{b} baskets.csv: 19 baskets, the first the initial one on T0, then 18 changes in date order", len(bb_) == 19 and bb_.role[0] == "initial" and (bb_.role[1:] == "change").all() and bb_.session_date[0] == str(T0.date()) and list(bb_.basket_no) == list(range(19)) and list(bb_.available_date) == sorted(bb_.available_date))
        sess_exp = [cal_all[int(cal_all.searchsorted(pd.Timestamp(x)))] for x in bb_.available_date]
        chk(f"{b} baskets.csv: session_date = the first session on or after availableDate, idx its position", [str(x.date()) for x in sess_exp] == list(bb_.session_date) and list(bb_.idx) == [int(cal_all.get_loc(x)) for x in sess_exp] and (bb_.n_held >= 1).all() and (bb_.raw_weight_sum.between(0.99, 1.01)).all())
        chk(f"{b} baskets on the page", all(f"<td>{b}</td><td>{len(bb_)}</td><td>18</td>" in html for _ in [0]))

    # 3. inputs
    chk("page's As-of date is APPROVED_DATA.md's", page["as_of_file"] == asof and asof in html, f"{page['as_of_file']} vs {asof}")
    rec = au.get("data", {}).get("approved_data_as_of")
    chk("the run recorded the same As-of date and the page prints it", page["as_of_inputs"] == rec == asof and rec in html, f"{page['as_of_inputs']} / {rec} vs {asof}")
    byfile = {r["file"].replace("\\", "/"): r for r in arows}
    chk("inputs listed (at least 30)", len(page["inputs"]) >= 30, str(len(page["inputs"])))
    need = ("nse_trading_days", "Master_Nifty100", "Master_MC100", "Master_SC100", "Master_MAUc1", "mauc1_daily_clean_extended", "why_gold_ohlc_eikon_extended", "LBES_Adjusted_Price_data_extended", "price_corrections", "SCMO_0003_ohlc",
            "SCMO_0007_ohlc", "SCMO_0010_ohlc", "SCMO_0029_ohlc", "SCMO_0003_holding_weight_matrix", "Rebalance_history_by_scid_SCMO_0029")
    chk("inputs include the calendar, the three Masters, MAUc1's Master and daily file, GOLDBEES, LBES, the corrections, the four stock files, baskets and rebalance histories", all(any(s_ in r["file"] for r in page["inputs"]) for s_ in need),
        str([s_ for s_ in need if not any(s_ in r["file"] for r in page["inputs"])]))
    chk("inputs include no D25 index file, no D24 / D09b / D12 file and no tag file", not any(s_ in r["file"] for r in page["inputs"] for s_ in ("_daily_ohlcv", "why_gold_ohlc_parent", "MAUc1/Master", "mcap", "membership", "symbology", "gold_daily_mcx")))
    for r in page["inputs"]:
        ar = byfile.get(r["file"].replace("\\", "/"))
        chk(f"input {r['file']} is a row of APPROVED_DATA.md", ar is not None)
        if ar is not None:
            chk(f"input {r['file']} is APPROVED, not superseded or pending", ar["status"] == "APPROVED", ar["status"])
            chk(f"input {r['file']} through-date", r["through"] == ar["through"], f"{r['through']} vs {ar['through']}")
            chk(f"input {r['file']} sha256 prefix", ar["sha"].startswith(r["sha16"][:len(ar["sha"])]) or r["sha16"].startswith(ar["sha"]), f"{r['sha16']} vs {ar['sha']}")
            mu = re.search(r"\[usable-from: (\d{4}-\d{2}-\d{2})\]", ar["note"])
            chk(f"input {r['file']} usable-from marker equals the registry's", (mu.group(1) if mu else "") == r["usable_from"], f"{r['usable_from']} vs {mu.group(1) if mu else ''}")
            if r["usable_from"]:
                chk(f"restricted input {r['file']} is read only from its usable-from date (window start {T0.date()})", pd.Timestamp(r["usable_from"]) <= T0)
            if re.match(r"\d{4}-\d{2}-\d{2}$", ar["through"]) and "published_nav" not in ar["file"]:
                chk(f"input {r['file']} covers the window end", ar["through"] >= page["end"], ar["through"])
            chk(f"page's table row for {r['file']} shows its through-date, row, sha256 prefix and usable-from", f"<tr><td>{H.escape(r['file'])}</td><td>{H.escape(ar['through'])}</td><td>{H.escape(r['approved_row'])}</td><td>{H.escape(r['sha16'])}</td><td>{H.escape(r['usable_from'])}</td></tr>" in html)
    # 4. page data -> evidence
    dd = lambda b, fam, win="full", cash="lbes", cost=20.8, mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    sv_of = lambda b, kind, c=20.8: nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").nav.values
    S1 = lambda b, kind, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == 20.8) & (st.kind == kind)].iloc[0]
    for b in BOOKS:
        pb = page["books"][b]
        for kind in KINDS:
            for c in (0.0, 20.8, 50.0):
                v = sv_of(b, kind, c)
                chk(f"{b} {kind} NAV starts at 1 ({c})", close(v[0], 1.0, 1e-12))
                chk(f"{b} {kind} CAGR and worst fall from NAV at {c}", close(pb[f"{kind}_cagr_{c:g}"], cagr(v)) and close(pb[f"{kind}_dd_{c:g}"], mdd(v)))
            v = sv_of(b, kind)
            chk(f"{b} {kind} CAGR, worst fall and end NAV at 20.8", close(pb[f"{kind}_cagr"], cagr(v)) and close(pb[f"{kind}_dd"], mdd(v)) and close(pb[f"{kind}_end"], float(v[-1])))
            chk(f"{b} {kind} NAV curve equals the stats.csv end NAV and CAGR", close(float(v[-1]), float(S1(b, kind).end_nav)) and close(cagr(v), float(S1(b, kind).cagr)))
        for base in R7_BASE:
            for var in R7_VARS:
                k7 = f"{base}_r7_{var}"
                for c in (0.0, 20.8):
                    s7 = st[(st.book == b) & (st.kind == k7) & (st.cost_bps == c) & (st.window == "full") & (st.cash == "lbes")]
                    v7 = sv_of(b, k7, c)
                    chk(f"{b} {k7} (R7) at {c:g}: stats.csv row equals the NAV's CAGR and worst fall; the NAV starts at 1", len(s7) == 1 and close(float(s7.iloc[0].cagr), cagr(v7)) and close(float(s7.iloc[0].max_dd), mdd(v7)) and close(v7[0], 1.0, 1e-12))
                chk(f"{b} {k7} (R7) on the page equals the NAV at 20.8 bps", close(pb[f"{k7}_cagr"], cagr(sv_of(b, k7))) and close(pb[f"{k7}_dd"], mdd(sv_of(b, k7))) and close(pb[f"{k7}_cagr_0"], cagr(sv_of(b, k7, 0.0))))
        if not (r7f.book == b).any():
            chk(f"{b} no stock-day is flagged: the R7 flagged re-runs equal their baselines", all(np.abs(sv_of(b, f"{base}_r7_flagged", c) / sv_of(b, base, c) - 1).max() < 1e-12 for base in R7_BASE for c in (0.0, 20.8)))
        x7 = r7x[r7x.book == b]
        chk(f"{b} r7_export.csv: the always-in 0-cost end NAV is the hold_parent run's, and without the export returns the hold_parent_r7_noexport run's", len(x7) > 0 and close(float(x7.end_nav_hold_parent.iloc[0]), float(sv_of(b, "hold_parent", 0.0)[-1]), 1e-9)
            and close(float(x7.end_nav_hold_parent_noexport.iloc[0]), float(sv_of(b, "hold_parent_r7_noexport", 0.0)[-1]), 1e-9) and (x7.end_nav_hold_parent == x7.end_nav_hold_parent.iloc[0]).all())
        chk(f"{b} r7 data on the page equal the files", page["r7"]["export"][b]["stocks"] == {str(r_.stock): int(r_.held_sessions_export) for r_ in x7.itertuples()} and close(page["r7"]["export"][b]["hold_end"], float(x7.end_nav_hold_parent.iloc[0]))
            and close(page["r7"]["export"][b]["hold_end_noexport"], float(x7.end_nav_hold_parent_noexport.iloc[0])) and page["caveats"][b]["held_export_sessions"] == int(x7.held_sessions_export.sum()) and page["caveats"][b]["flagged_days"] == int((r7f.book == b).sum()))
        pcs = {}
        for tag, (fam, mode, rk) in TAGS.items():
            sv = sv_of(b, rk)
            nd = dd(b, fam, mode=mode)
            chk(f"{b} {tag} draws count and ids", len(nd) == ND and list(nd.draw_id) == list(range(ND)), str(len(nd)))
            p1, q1, w1, t1, b1 = pctl(cagr(sv), nd.cagr.values)
            p2, q2, *_ = pctl(mdd(sv), nd.max_dd.values)
            pcs[tag] = (q1, q2)
            chk(f"{b} {tag} CAGR percentile and p", close(pb[f"{tag}_pct_cagr"], p1) and close(pb[f"{tag}_p_cagr"], q1) and (pb[f"{tag}_worse"], pb[f"{tag}_tied"], pb[f"{tag}_better"]) == (w1, t1, b1))
            chk(f"{b} {tag} drawdown percentile and p", close(pb[f"{tag}_pct_dd"], p2) and close(pb[f"{tag}_p_dd"], q2))
            chk(f"{b} {tag} medians", close(pb[f"{tag}_median_cagr"], float(nd.cagr.median())) and close(pb[f"{tag}_median_dd"], float(nd.max_dd.median())))
            chk(f"{b} {tag} SD and MDE", close(pb[f"{tag}_sd_cagr"], float(nd.cagr.std())) and close(pb[f"{tag}_mde_cagr_pp"], 280 * float(nd.cagr.std())) and close(pb[f"{tag}_mde_dd_pp"], 280 * float(nd.max_dd.std())) and close(pb[f"{tag}_sd_dd"], float(nd.max_dd.std())))
            q5, q95 = np.percentile(nd.cagr.values, [5, 95])
            chk(f"{b} {tag} 5th and 95th percentile of CAGR", close(pb[f"{tag}_p5_cagr"], float(q5)) and close(pb[f"{tag}_p95_cagr"], float(q95)))
            chk(f"{b} {tag} sessions invested summary", (pb[f"{tag}_sess_min"], pb[f"{tag}_sess_max"]) == (int(nd.sessions_invested.min()), int(nd.sessions_invested.max())) and close(pb[f"{tag}_sess_median"], float(nd.sessions_invested.median())))
            chk(f"{b} {tag} sleeve trades summary", (pb[f"{tag}_strades_min"], pb[f"{tag}_strades_max"]) == (int(nd.sleeve_trades.min()), int(nd.sleeve_trades.max())) and close(pb[f"{tag}_strades_median"], float(nd.sleeve_trades.median())))
            if tag != "F5":
                for c in (0.0, 50.0):
                    vv = sv_of(b, rk, c)
                    nc = dd(b, fam, cost=c, mode=mode)
                    chk(f"{b} {tag} CAGR percentile at {c}", close(pb[f"{tag}_pct_cagr_{c:g}"], pctl(cagr(vv), nc.cagr.values)[0]))
                    chk(f"{b} {tag} drawdown percentile at {c}", close(pb[f"{tag}_pct_dd_{c:g}"], pctl(mdd(vv), nc.max_dd.values)[0]))
            if mode == "fixed50":
                chk(f"{b} {tag} (50/50 sleeve) rows have no sleeve trades and the gold column is real", int(nd.sleeve_trades.sum()) == 0 and set(nd.gold_null) == {"real"})
        h_ = holm([pcs["F1f"][0], pcs["F1f"][1], pcs["F1"][0], pcs["F1"][1], pcs["F3"][0], pcs["F3"][1]])
        chk(f"{b} Holm-adjusted p over A1, A2, C1 to C4 (m = 6)", all(close(pb[f"holm_{cr}"], h_[i]) for i, cr in enumerate(("A1", "A2", "C1", "C2", "C3", "C4"))), str(h_))
        for tag in ("F1f", "F1", "F3"):
            fam, mode, rk = TAGS[tag]
            s_r3, s_lq = S1(b, rk, win="r3"), S1(b, rk, cash=LIQ)
            chk(f"{b} {tag} R3 percentile", close(pb[f"{tag}_r3_pct"], pctl(float(s_r3.cagr), dd(b, fam, win="r3", mode=mode).cagr.values)[0]))
            chk(f"{b} {tag} LIQUIDCASE percentile", close(pb[f"{tag}_liq_pct"], pctl(float(s_lq.cagr), dd(b, fam, cash=LIQ, mode=mode).cagr.values)[0]))
        chk(f"{b} R2/R3 rule CAGRs", close(pb["r3_cagr"], float(S1(b, "strategy", win="r3").cagr)) and close(pb["r3_fixed50_cagr"], float(S1(b, "strategy_fixed50", win="r3").cagr)) and close(pb["liq_cagr"], float(S1(b, "strategy", cash=LIQ).cagr)) and close(pb["liq_fixed50_cagr"], float(S1(b, "strategy_fixed50", cash=LIQ).cagr)))
        sv, sf = sv_of(b, "strategy"), sv_of(b, "strategy_fixed50")
        dr_c, dr_d = cagr(sv) - cagr(sf), mdd(sv) - mdd(sf)
        chk(f"{b} R6 rule change from 50/50 to timed", close(pb["r6_rule_dcagr"], dr_c) and close(pb["r6_rule_ddd"], dr_d))
        for fam in ("F1", "F2"):
            t_, f_ = dd(b, fam), dd(b, fam, mode="fixed50")
            chk(f"{b} R6 {fam}: same draw ids timed and fixed50", list(t_.draw_id) == list(f_.draw_id) == list(range(ND)))
            dcs, dds = t_.cagr.values - f_.cagr.values, t_.max_dd.values - f_.max_dd.values
            chk(f"{b} R6 {fam} medians, percentiles, shares", close(pb[f"r6_{fam}_median_dcagr"], float(np.median(dcs))) and close(pb[f"r6_{fam}_pct_dcagr"], pctl(dr_c, dcs)[0]) and close(pb[f"r6_{fam}_share_dcagr"], float((dcs > 0).mean()))
                and close(pb[f"r6_{fam}_median_ddd"], float(np.median(dds))) and close(pb[f"r6_{fam}_pct_ddd"], pctl(dr_d, dds)[0]) and close(pb[f"r6_{fam}_share_ddd"], float((dds > 0).mean())))
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        cl = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").date.values
        w0 = [0] + [len(cl) - 1 if pd.isna(t) else int(np.searchsorted(cl, np.datetime64(pd.Timestamp(t)))) for t in e.trade_date.iloc[1:]]
        ws = np.array(w0[1:] + [len(cl) - 1]) - np.array(w0)
        chk(f"{b} rule sessions invested and total", pb["rule_sessions"] == int(rule[b] @ ws) and pb["sessions_total"] == len(cl) - 1)
        for fam, key in (("F1", "io|N4.10"), ("F2", "io|N4.9")):
            for mode in ("timed", "fixed50"):
                chk(f"{b} {fam} ({mode}) sessions_invested column equals states @ sessions per week", bool((ST[f"{b}|full|{key}"].astype(np.int64) @ ws == dd(b, fam, mode=mode).sessions_invested.values).all()))
        for fam in ("F3", "F4"):
            chk(f"{b} {fam} sessions_invested equal the rule's (the real switch)", bool((dd(b, fam).sessions_invested.values == int(rule[b] @ ws)).all()))
        s_row = S1(b, "strategy")
        chk(f"{b} cost paid, trades, sleeve trades and basket changes", close(pb["cost_paid"], float(s_row.cost_paid)) and pb["trades"] == int(s_row.trades) and pb["sleeve_trades"] == int(s_row.sleeve_trades) and pb["basket_trades"] == int(s_row.basket_trades))
        chk(f"{b} invested weeks equal the decisions'", int(s_row.invested_weeks) == int(rule[b].sum()))
        rt = lambda a_: min(int(((a_[1:] == 1) & (a_[:-1] == 0)).sum()) + int(a_[0] == 1), int(((a_[1:] == 0) & (a_[:-1] == 1)).sum()))

        def gwo(g, s):
            k_, i_ = 0, 0
            for v_, ln in spells(g):
                k_ += int((s[i_:i_ + ln] == 0).any())
                i_ += ln
            return k_
        chk(f"{b} round trips and gold spells with an OUT week (full and R3)", pb["round_trips"] == rt(rule[b]) and pb["gold_spells_with_out"] == gwo(gold[b], rule[b]) and pb["r3_round_trips"] == rt(r3_io[b]) and pb["r3_gold_spells_with_out"] == gwo(r3_g[b], r3_io[b]))
        trad = [j for j in range(1, len(e)) if not pd.isna(e.trade_date[j])]
        exp_reb = [j for j in trad if rule[b][j - 1] == 0 and rule[b][j] == 0 and gold[b][j] != gold[b][j - 1]]
        sq = sl[(sl.book == b) & (sl.cost_bps == 20.8) & (sl.kind == "sleeve_rebalance")]
        chk(f"{b} sleeve rebalances: number and dates from the decisions", len(sq) == len(exp_reb) == pb["sleeve_trades"] and sorted(sq.date) == sorted(e.trade_date[exp_reb]), f"{len(sq)} vs {len(exp_reb)}")
    nrp = page["not_reportable"]
    nr_io = [b for b in BOOKS if page["books"][b]["round_trips"] < 4]
    nr_gold = [b for b in BOOKS if page["books"][b]["gold_spells_with_out"] < 4]
    nr_io3 = [b for b in BOOKS if page["books"][b]["r3_round_trips"] < 4]
    nr_gold3 = [b for b in BOOKS if page["books"][b]["r3_gold_spells_with_out"] < 4]
    chk("reportability lists (feasibility is checked with the count tables below)", nrp == {"io": nr_io, "gold": nr_gold, "io_r3": nr_io3, "gold_r3": nr_gold3}, f"{nrp} vs {nr_io} {nr_gold} {nr_io3} {nr_gold3}")
    V = page["verdict"]
    nrc = lambda cr, r3=False: (nr_io3 if r3 else nr_io) + ((nr_gold3 if r3 else nr_gold) if cr in ("C3", "C4") else [])
    cnt = lambda key, cr, r3=False: sum(page["books"][b][key] >= 90 and b not in nrc(cr, r3) for b in BOOKS)
    exp_v = {}
    for cr, stat, td, tb in CRIT:
        sfx = "dd" if stat == "max_dd" else "cagr"
        exp_v[cr], exp_v[cr + "_beside"] = cnt(f"{td}_pct_{sfx}", cr), cnt(f"{tb}_pct_{sfx}", cr)
    for tag, cr in (("F1f", "A1"), ("F1", "C1"), ("F3", "C3")):
        exp_v[f"R3_{cr}"], exp_v[f"R2_{cr}"] = cnt(f"{tag}_r3_pct", cr, True), cnt(f"{tag}_liq_pct", cr)
    chk("verdict counts", V == exp_v, f"{V} vs {exp_v}")
    A_ok, C_ok, G_ok = V["A1"] >= 3 and V["A2"] >= 3, V["C1"] >= 3 and V["C2"] >= 3, V["C3"] >= 3 and V["C4"] >= 3
    chk("outcome flags on the page", page["outcome"] == {"A": bool(A_ok), "C": bool(C_ok), "G": bool(G_ok)})
    # historical references: stored draws of T06 and T08, shown only if the files exist
    ref = page["historical_reference"]
    if (t06 / "draws.csv").exists() and (t06 / "stats.csv").exists():
        s6 = pd.read_csv(t06 / "stats.csv")
        d6 = pd.read_csv(t06 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "draw_type", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == 20.8) & (s6.kind == "strategy")].iloc[0]
            tr_ = ref["T06"].get(b)
            ok = tr_ is not None and close(tr_["cagr"], float(sr.cagr))
            for typ, nm in (("N4.10", "n10"), ("N4.9", "n9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == 20.8) & (d6.draw_type == typ)]
                ok = ok and tr_ is not None and close(tr_[f"{nm}_pct_cagr"], pctl(sr.cagr, nd_.cagr.values)[0]) and close(tr_[f"{nm}_pct_dd"], pctl(sr.max_dd, nd_.max_dd.values)[0])
            chk(f"{b} T06 historical reference", ok)
    else:
        chk("T06 reference: evidence not found, so the page carries none and says so", ref["T06"] == {} and "Historical reference to T06: omitted" in text)
    if (t08 / "draws.csv").exists() and (t08 / "stats.csv").exists():
        s8 = pd.read_csv(t08 / "stats.csv")
        d8 = pd.read_csv(t08 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s8[(s8.book == b) & (s8.window == "full") & (s8.cash == "lbes") & (s8.cost_bps == 20.8) & (s8.kind == "strategy")].iloc[0]
            tr_ = ref["T08"].get(b)
            ok = tr_ is not None and close(tr_["cagr"], float(sr.cagr))
            for fam in ("F1", "F2", "F3", "F4"):
                nd_ = d8[(d8.book == b) & (d8.window == "full") & (d8.cash == "lbes") & (d8.cost_bps == 20.8) & (d8.family == fam) & (d8.sleeve_mode == "timed")]
                ok = ok and tr_ is not None and close(tr_[f"{fam}_pct_cagr"], pctl(sr.cagr, nd_.cagr.values)[0]) and close(tr_[f"{fam}_pct_dd"], pctl(sr.max_dd, nd_.max_dd.values)[0])
            chk(f"{b} T08 historical reference", ok)
    else:
        chk("T08 reference: evidence not found, so the page carries none and says so", ref["T08"] == {} and "Historical reference to T08: omitted" in text)
    if (t09 / "draws.csv").exists() and (t09 / "stats.csv").exists():
        s9 = pd.read_csv(t09 / "stats.csv")
        d9 = pd.read_csv(t09 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s9[(s9.book == b) & (s9.window == "full") & (s9.cash == "lbes") & (s9.cost_bps == 20.8) & (s9.kind == "strategy")].iloc[0]
            tr_ = ref["T09"].get(b)
            ok = tr_ is not None and close(tr_["cagr"], float(sr.cagr))
            for tag, fam, mode, rk_kind in (("F1f", "F1", "fixed50", "strategy_fixed50"), ("F1", "F1", "timed", "strategy"), ("F2", "F2", "timed", "strategy"), ("F3", "F3", "timed", "strategy"), ("F4", "F4", "timed", "strategy")):
                sk = s9[(s9.book == b) & (s9.window == "full") & (s9.cash == "lbes") & (s9.cost_bps == 20.8) & (s9.kind == rk_kind)].iloc[0]
                nd_ = d9[(d9.book == b) & (d9.window == "full") & (d9.cash == "lbes") & (d9.cost_bps == 20.8) & (d9.family == fam) & (d9.sleeve_mode == mode)]
                ok = ok and tr_ is not None and close(tr_[f"{tag}_pct_cagr"], pctl(float(sk.cagr), nd_.cagr.values)[0]) and close(tr_[f"{tag}_pct_dd"], pctl(float(sk.max_dd), nd_.max_dd.values)[0])
            chk(f"{b} T09 historical reference", ok)
        t9 = {cr: sum(1 for b in BOOKS if ref["T09"][b][f"{TAG_OF[cr][0]}_pct_{TAG_OF[cr][2]}"] >= 90) for cr in TAG_OF}
        chk("T09 verdict counts on the page", page["t09_counts"] == t9, f"{page['t09_counts']} vs {t9}")
    else:
        chk("T09 reference: evidence not found, so the page carries none and says so", ref["T09"] == {} and "Historical reference to T09: omitted" in text and page["t09_counts"] is None)

    # 5. the samplers from scratch
    cte = {}
    for key, o in ct["tables"].items():
        p_ = key.split("|")
        cte[tuple(p_)] = {"k": int(o.get("spells_k", o.get("k"))), "S": int(o.get("weeks_S", o.get("S"))), "lo": int(o["lo"]), "hi": int(o["hi"]), "n_ways": int(o["n_ways"])}
    real = {("full", "io"): rule, ("full", "gold"): gold, ("r3", "io"): r3_io, ("r3", "gold"): r3_g}
    for b in BOOKS:
        for win in ("full", "r3"):
            for kind, sts in (("io", (("in", 1), ("out", 0))), ("gold", (("buy", 1), ("sell", 0)))):
                for nm, v_ in sts:
                    e = cte.get((b, win, kind, nm))
                    chk(f"count_table entry {b}/{win}/{kind}/{nm}", e is not None)
                    if e:
                        ls = lens(real[(win, kind)][b], v_)
                        lo_, hi_ = bounds_of(real[(win, kind)][b])[v_]
                        chk(f"count_table {b}/{win}/{kind}/{nm}: bounds (lo = min(2, shortest), hi = longest) and feasibility", (e["lo"], e["hi"]) == (lo_, hi_) and e["lo"] * e["k"] <= e["S"] <= e["hi"] * e["k"])
                        chk(f"count_table {b}/{win}/{kind}/{nm}: k and S are the real series'", (e["k"], e["S"]) == (len(ls), sum(ls)))
                        chk(f"count_table {b}/{win}/{kind}/{nm}: n_ways = inclusion-exclusion = own DP", e["n_ways"] == ways_ie(e["k"], e["S"], lo_, hi_) == dp(e["k"], e["S"], lo_, hi_)[e["k"]][e["S"]], str(e["n_ways"]))
    ex = page["example"]
    b = B0
    kin, Sin, kout, Sout = len(rin[b]), sum(rin[b]), len(rout[b]), sum(rout[b])
    kb, Sb, ks_, Ss_ = len(gbuy[b]), sum(gbuy[b]), len(gsell[b]), sum(gsell[b])
    bi, bg = BNDF["io"], BNDF["gold"]
    chk("example sampler parameters", (ex["k_in"], ex["S_in"], ex["lo_in"], ex["hi_in"], ex["k_out"], ex["S_out"], ex["lo_out"], ex["hi_out"], ex["k_buy"], ex["S_buy"], ex["lo_buy"], ex["hi_buy"], ex["k_sell"], ex["S_sell"], ex["lo_sell"], ex["hi_sell"]) ==
        (kin, Sin, *bi[1], kout, Sout, *bi[0], kb, Sb, *bg[1], ks_, Ss_, *bg[0]))
    chk("example allowed-tuple counts", int(ex["ways_in"]) == int(ex["ways_in_table"]) == ways_ie(kin, Sin, *bi[1]) and int(ex["ways_out"]) == int(ex["ways_out_table"]) == ways_ie(kout, Sout, *bi[0])
        and int(ex["ways_buy"]) == int(ex["ways_buy_table"]) == ways_ie(kb, Sb, *bg[1]) and int(ex["ways_sell"]) == int(ex["ways_sell_table"]) == ways_ie(ks_, Ss_, *bg[0]))
    chk("the four tuple counts of T11.md section 3 (4,024,559,144; 19,406,343,528; 6,835,192,844,305; 4,976,743,356)",
        (int(ex["ways_in"]), int(ex["ways_out"]), int(ex["ways_buy"]), int(ex["ways_sell"])) == (4024559144, 19406343528, 6835192844305, 4976743356))
    for tag, seed, names, ks, Ss, bnds, stk, key in (("F1", [14, 6, 0], ("in", "out"), {"in": kin, "out": kout}, {"in": Sin, "out": Sout}, {"in": bi[1], "out": bi[0]}, "steps", "io|N4.10"),
                                                     ("F3", [14, 11, 6, 0], ("buy", "sell"), {"buy": kb, "sell": ks_}, {"buy": Sb, "sell": Ss_}, {"buy": bg[1], "sell": bg[0]}, "steps_g", "gold|N4.10-g")):
        rp = replay(seed, names, ks, Ss, bnds)
        mine = [(s_, p_) for s_ in names for p_ in rp[s_]]
        chk(f"{tag} example replay: same number of steps", len(ex[stk]) == len(mine) == sum(ks.values()))
        for stp, (sp, (x, u, tot, wx)) in zip(ex[stk], mine):
            chk(f"{tag} example replay step", stp["spell"] == sp and stp["x"] == x and close(stp["u"], u, 1e-12) and stp["total"] == tot and stp["ways_x"] == wx and close(stp["p"], wx / tot, 1e-9), str(stp))
        Zk = ST[f"{b}|full|{key}"]
        mine_a, mine_b = [p_[0] for p_ in rp[names[0]]], [p_[0] for p_ in rp[names[1]]]
        chk(f"{tag} example replay equals the stored draw 0 (states file)", mine_a == lens(Zk[0], 1) and mine_b == lens(Zk[0], 0), f"{mine_a} {mine_b} vs {lens(Zk[0], 1)} {lens(Zk[0], 0)}")
        chk(f"{tag} example replay flag on the page", (ex["replay_ok"] if tag == "F1" else ex["replay_ok_g"]) is True)
        x_ = dd(b, tag).query("draw_id == 0").iloc[0]
        s_a, s_b = ("in_lengths", "out_lengths") if tag == "F1" else ("g_buy_lengths", "g_sell_lengths")
        chk(f"{tag} example draw 0 lengths in draws.csv equal the replay", str(x_[s_a]) == "|".join(map(str, mine_a)) and str(x_[s_b]) == "|".join(map(str, mine_b)))
    chk("page says both replays equal the stored draws", html.count("replay equals the stored draw") == 2)
    chk("first-step weights (F1 and F3)", page["sampler_first"]["weights"] == [dp(kin, Sin, *bi[1])[kin - 1][Sin - x] if Sin - x >= 0 else 0 for x in range(bi[1][0], bi[1][1] + 1)] and sum(page["sampler_first"]["weights"]) == int(ex["ways_in"])
        and page["sampler_first_g"]["weights"] == [dp(kb, Sb, *bg[1])[kb - 1][Sb - x] if Sb - x >= 0 else 0 for x in range(bg[1][0], bg[1][1] + 1)] and sum(page["sampler_first_g"]["weights"]) == int(ex["ways_buy"]))
    for tag in ("F1", "F2", "F3", "F4", "F1f", "F2f"):
        fam, mode, rk = TAGS[tag]
        x_ = dd(b, fam, mode=mode).query("draw_id == 0").iloc[0]
        e_ = ex["d0"][tag]
        chk(f"example {tag} draw 0 numbers", close(e_["cagr"], float(x_.cagr)) and close(e_["max_dd"], float(x_.max_dd)) and e_["sessions"] == int(x_.sessions_invested) and e_["sleeve_trades"] == int(x_.sleeve_trades))
        rk_ = ex["rank"][tag]
        nd = dd(b, fam, mode=mode)
        chk(f"example ranking against {tag} adds up", rk_["worse"] + rk_["tied"] + rk_["better"] == rk_["draws"] == ND == len(nd))
        chk(f"example percentile and p against {tag}", close(rk_["percentile"], (rk_["worse"] + 0.5 * rk_["tied"]) / ND * 100) and close(rk_["p"], (1 + rk_["better"] + rk_["tied"]) / (ND + 1)) and close(rk_["percentile"], page["books"][b][f"{tag}_pct_cagr"]))
    # regeneration of the first draws of all four samplers from their seeds, and shared draws across books
    R = min(a.regen, ND)
    for typ, kind, real_s in (("N4.9", "io", rule[B0]), ("N4.10", "io", rule[B0]), ("N4.9-g", "gold", gold[B0]), ("N4.10-g", "gold", gold[B0])):
        A = ST[f"{B0}|full|{kind}|{typ}"]
        f_ = regen_shuffle if typ.startswith("N4.9") else regen_free
        okr = all((f_(real_s, i, SEEDS[typ]) == A[i].astype(int)).all() for i in range(R))
        chk(f"the first {R} draws of {typ} regenerated here from default_rng({list(SEEDS[typ])} + [id]) equal draw_states.npz", okr)
        for bx in BOOKS[1:]:
            chk(f"{typ}: {bx} shares the draws of {B0}", (ST[f"{bx}|full|{kind}|{typ}"] == A).all())
    # the worked trades: identities, units (positions.csv), dates
    e0 = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    exx, exf, exn, exb = ex["exit"], ex["flip"], ex["entry"], ex["basket"]
    slq = sl[(sl.book == b) & (sl.cost_bps == 20.8)]
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == 20.8)].sort_values("idx").reset_index(drop=True)
    poq = po[(po.book == b) & (po.cost_bps == 20.8) & (po.run == "strategy")]
    bkq = bsk[bsk.book == b].sort_values("basket_no").reset_index(drop=True)
    NS = ("GOLDBEES", "LBES")

    def snap(date):
        x = poq[poq.date.astype(str) == str(date)]
        stocks = [(str(r_.instrument), float(r_.units)) for r_ in x.itertuples() if r_.instrument not in NS]
        return {"date": str(date), "n_stock": len(stocks), "first3": [[n_, u_] for n_, u_ in stocks[:3]], "GOLDBEES": float(x[x.instrument == "GOLDBEES"].units.sum()), "LBES": float(x[x.instrument == "LBES"].units.sum()),
                "_stocks": dict(stocks)}

    def around(date):
        i = int(trq.index[trq.date.astype(str) == str(date)][0])
        return (snap(trq.date[i - 1]) if i > 0 else None), snap(date)

    def same_units(page_u, mine):
        return page_u is not None and mine is not None and {k_: v_ for k_, v_ in mine.items() if k_ != "_stocks"} == page_u

    first_i = lambda kind_: next(i_ for i_ in range(1, len(trq)) if trq.kind[i_] == kind_)
    tx, tf, tn, tb = (trq.iloc[first_i(k_)] for k_ in ("switch_out", "sleeve_rebalance", "switch_in", "basket_change"))
    nheld = {str(r_.available_date): int(r_.n_held) for r_ in bkq.itertuples()}
    chk("example: each worked trade is the first of its kind (with a trade before it) in trades.csv, strategy, 20.8 bps", exx["trade_date"] == str(tx.date) and exf["trade_date"] == str(tf.date) and exn["trade_date"] == str(tn.date) and exb["trade_date"] == str(tb.date))
    # exit
    jx = int(e0.index[e0.trade_date == tx.date][0])
    chk("example exit: an IN to OUT decision; dates, signal and weights", rule[b][jx - 1] == 1 and rule[b][jx] == 0 and jx == exx["decision_week"] and exx["decision_date"] == str(e0.decision_date[jx]) and exx["g"] == int(gold[b][jx]) and close(exx["gw"], 0.8 if gold[b][jx] else 0.2) and exx["sign_MAUc1"] == ("BUY" if gold[b][jx] else "SELL"))
    sqx = slq[slq.date.astype(str) == str(tx.date)].iloc[0]
    chk("example exit: numbers equal trades.csv and sleeve_trades.csv", close(exx["V"], float(tx.V)) and close(exx["traded"], float(sqx.traded)) and close(exx["cost"], float(sqx.cost)) and close(exx["nav_after"], float(tx.nav_close_after))
        and close(exx["gold_after"], float(sqx.gold_value_after)) and close(exx["cash_after"], float(sqx.cash_value_after)) and exx["raw_fill"] == bool(sqx.gold_fill_raw) and sqx.kind == "switch_out")
    chk("example exit: cost = traded x 20.8/2/10000; GOLDBEES = w (V - cost), cash = (1 - w)(V - cost)", close(exx["cost"], exx["traded"] * 20.8 / 2 / 10000, 1e-9) and close(exx["gold_after"], exx["gw"] * (exx["V"] - exx["cost"]), 1e-9) and close(exx["cash_after"], (1 - exx["gw"]) * (exx["V"] - exx["cost"]), 1e-9))
    ub, ua = around(tx.date)
    chk("example exit: units before and after are positions.csv's; the book held stocks only before and GOLDBEES and cash only after", same_units(exx["units_before"], ub) and same_units(exx["units_after"], ua) and ub["n_stock"] > 0 and ub["GOLDBEES"] == 0 and ub["LBES"] == 0 and ua["n_stock"] == 0 and ua["GOLDBEES"] > 0 and ua["LBES"] > 0)
    chk("example exit: the stock lines held before are the basket in force's (n_held)", ub["n_stock"] == nheld[str(trq.basket_eff[first_i("switch_out") - 1])])
    # flip
    fr = slq[slq.date.astype(str) == str(tf.date)].iloc[0]
    jf = int(e0.index[e0.trade_date == tf.date][0])
    chk("example flip: OUT on both sides, signal changed, dates", rule[b][jf - 1] == 0 and rule[b][jf] == 0 and gold[b][jf] != gold[b][jf - 1] and exf["decision_week"] == jf and exf["decision_date"] == str(e0.decision_date[jf])
        and exf["g_before"] == int(gold[b][jf - 1]) and exf["g_after"] == int(gold[b][jf]) and close(exf["gw_after"], 0.8 if gold[b][jf] else 0.2) and fr.kind == "sleeve_rebalance")
    chk("example flip: numbers equal trades.csv and sleeve_trades.csv", close(exf["V"], float(tf.V)) and close(exf["traded"], float(fr.traded)) and close(exf["cost"], float(fr.cost)) and close(exf["nav_after"], float(tf.nav_close_after))
        and close(exf["gold_before"], float(fr.gold_value_before)) and close(exf["cash_before"], float(fr.cash_value_before)) and close(exf["gold_after"], float(fr.gold_value_after)) and close(exf["cash_after"], float(fr.cash_value_after)) and exf["raw_fill"] == bool(fr.gold_fill_raw))
    chk("example flip: cost, value conserved after cost, split = target", close(exf["cost"], exf["traded"] * 20.8 / 2 / 10000, 1e-9) and close(exf["gold_before"] + exf["cash_before"] - exf["cost"], exf["gold_after"] + exf["cash_after"], 1e-9) and close(exf["gold_after"], exf["gw_after"] * (exf["gold_after"] + exf["cash_after"]), 1e-9))
    ub, ua = around(tf.date)
    chk("example flip: units equal positions.csv; the fill price (value / units) is the same before and after for GOLDBEES and cash", same_units(exf["units_before"], ub) and same_units(exf["units_after"], ua) and ub["n_stock"] == 0 and ua["n_stock"] == 0
        and close(exf["gold_before"] / ub["GOLDBEES"], exf["gold_after"] / ua["GOLDBEES"], 1e-9) and close(exf["cash_before"] / ub["LBES"], exf["cash_after"] / ua["LBES"], 1e-9))
    # entry
    jn = int(e0.index[e0.trade_date == tn.date][0])
    chk("example entry: a decision OUT to IN, all three index signs BUY, dates", rule[b][jn - 1] == 0 and rule[b][jn] == 1 and exn["decision_week"] == jn and exn["decision_date"] == str(e0.decision_date[jn]) and exn["sign"] == ["BUY", "BUY", "BUY"] and exn["sign_MAUc1"] == ("BUY" if gold[b][jn] else "SELL"))
    chk("example entry: numbers equal trades.csv; cost identity; the sleeve is sold (traded >= V)", close(exn["V"], float(tn.V)) and close(exn["traded"], float(tn.traded)) and close(exn["cost"], float(tn.cost)) and close(exn["nav_after"], float(tn.nav_close_after)) and close(exn["cost"], exn["traded"] * 20.8 / 2 / 10000, 1e-9)
        and exn["traded"] > exn["V"] and exn["basket_eff"] == str(tn.basket_eff))
    ub, ua = around(tn.date)
    chk("example entry: units equal positions.csv; as many stock lines as the basket in force lists; no GOLDBEES or cash left", same_units(exn["units_before"], ub) and same_units(exn["units_after"], ua) and ua["n_stock"] == nheld[str(tn.basket_eff)] and ua["GOLDBEES"] == 0 and ua["LBES"] == 0 and ub["n_stock"] == 0)
    # basket change
    nbk_ = bkq[bkq.available_date.astype(str) == str(tb.basket_eff)].iloc[0]
    chk("example basket change: the first one of the rule; on its basket's session; no decision trade that day; the stock share stays 1", exb["trade_date"] == str(nbk_.session_date) == str(tb.date) and exb["basket_no"] == int(nbk_.basket_no) and exb["available_date"] == str(nbk_.available_date)
        and exb["session_date"] == str(nbk_.session_date) and exb["n_held"] == int(nbk_.n_held) and close(exb["raw_weight_sum"], float(nbk_.raw_weight_sum), 1e-12) and tb.e_after == 1.0 and str(tb.date) not in set(trq[trq.kind != "basket_change"].date.astype(str)))
    chk("example basket change: numbers equal trades.csv; cost identity", close(exb["V"], float(tb.V)) and close(exb["traded"], float(tb.traded)) and close(exb["cost"], float(tb.cost)) and close(exb["nav_after"], float(tb.nav_close_after)) and close(exb["cost"], exb["traded"] * 20.8 / 2 / 10000, 1e-9))
    ub, ua = around(tb.date)
    lost, gain = sorted(k_ for k_ in ub["_stocks"] if k_ not in ua["_stocks"]), sorted(k_ for k_ in ua["_stocks"] if k_ not in ub["_stocks"])
    kept = [k_ for k_ in ua["_stocks"] if k_ in ub["_stocks"]]
    chk("example basket change: units equal positions.csv; the lines after are the new basket's n_held; sold out, bought and resized stocks recomputed", same_units(exb["units_before"], ub) and same_units(exb["units_after"], ua) and ua["n_stock"] == int(nbk_.n_held)
        and exb["sold_out"] == lost and exb["newly_bought"] == gain and exb["kept"] == len(kept) and exb["kept_resized"] == int(sum(abs(ua["_stocks"][k_] / ub["_stocks"][k_] - 1) > 1e-9 for k_ in kept)) and ub["GOLDBEES"] == 0 and ua["GOLDBEES"] == 0)
    nvb = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nvb.index[nvb.date == pd.Timestamp(exx["trade_date"])][0])
    for r_ in nvb.loc[k - 2:k + 2].itertuples():
        chk(f"page prints NAV {r_.date.date()} {r_.nav:.6f}", f"<td>{r_.date.date()}</td><td>{r_.nav:.6f}</td>" in html)
    chk("example path numbers", ex["sessions"] == len(nvb) and close(ex["end_nav"], float(nvb.nav.iloc[-1])) and close(ex["cagr"], cagr(nvb.nav.values)) and close(ex["max_dd"], mdd(nvb.nav.values)))

    # 7. every trade row of the evidence
    tot_a = sl.gold_value_after + sl.cash_value_after
    chk("sleeve_trades.csv: cost = traded x cost_bps / 2 / 10000 on every row", bool(((sl.cost - sl.traded * sl.cost_bps / 2 / 1e4).abs() <= 1e-9 * np.maximum(1, sl.traded)).all()))
    chk("sleeve_trades.csv: GOLDBEES share after the trade is the target weight on every row", bool(((sl.gold_value_after / tot_a - sl.gw_after).abs() < 1e-9).all()))
    chk("sleeve_trades.csv: a rebalance conserves value after cost on every row", bool((((sl.gold_value_before + sl.cash_value_before - sl.cost - tot_a).abs() < 1e-9) | (sl.kind != "sleeve_rebalance")).all()))
    chk("trades.csv: cost = traded x cost_bps / 2 / 10000 on every row of every run", bool(((tr.cost - tr.traded * tr.cost_bps / 2 / 1e4).abs() <= 1e-9 * np.maximum(1, tr.traded)).all()))
    for bk in BOOKS:
        e = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
        trad = [j for j in range(1, len(e)) if not pd.isna(e.trade_date[j])]
        exp_n = {"switch_out": len([j for j in trad if rule[bk][j - 1] == 1 and rule[bk][j] == 0]), "switch_in": len([j for j in trad if rule[bk][j - 1] == 0 and rule[bk][j] == 1]),
                 "sleeve_rebalance": len([j for j in trad if rule[bk][j - 1] == 0 and rule[bk][j] == 0 and gold[bk][j] != gold[bk][j - 1]])}
        bb_ = bsk[bsk.book == bk].sort_values("basket_no").reset_index(drop=True)
        chg = {int(r_.idx): str(r_.available_date) for r_ in bb_[bb_.role == "change"].itertuples()}
        for c in (0.0, 20.8, 50.0):
            sc_ = sl[(sl.book == bk) & (sl.cost_bps == c)]
            chk(f"{bk} {c}: sleeve_trades.csv holds exactly the exits and sleeve rebalances of the decisions (numbers and dates)", sorted(sc_[sc_.kind == "sleeve_rebalance"].date) == sorted(e.trade_date[[j for j in trad if rule[bk][j - 1] == 0 and rule[bk][j] == 0 and gold[bk][j] != gold[bk][j - 1]]])
                and sorted(sc_[sc_.kind == "switch_out"].date) == sorted(e.trade_date[[j for j in trad if rule[bk][j - 1] == 1 and rule[bk][j] == 0]]))
            t_ = tr[(tr.book == bk) & (tr.cost_bps == c) & (tr.run == "strategy")]
            got = {k_: int((t_.kind == k_).sum()) for k_ in exp_n}
            chk(f"{bk} {c}: numbers of exits, entries and sleeve rebalances from the decisions", got == exp_n, f"{got} vs {exp_n}")
            dts = set(int(i_) for i_ in t_[t_.kind != "basket_change"].idx)
            ev_ = [(int(r_.idx), float(r_.e_after)) for r_ in t_.itertuples() if r_.kind != "basket_change"]
            exp_b = []
            for q_ in sorted(chg):
                h_ = float(rule[bk][0])
                for ti_, ea in ev_:
                    if ti_ < q_:
                        h_ = ea
                if h_ > 0 and q_ not in dts:
                    exp_b.append(q_)
            chk(f"{bk} {c}: basket changes are the baskets.csv sessions at which the book holds the parent and no decision trade falls", sorted(int(i_) for i_ in t_[t_.kind == "basket_change"].idx) == exp_b, f"{len(exp_b)} expected")
            hp_t = tr[(tr.book == bk) & (tr.cost_bps == c) & (tr.run == "hold_parent")]
            chk(f"{bk} {c}: hold-the-parent trades are the {len(chg)} basket changes, one on each basket session", sorted(int(i_) for i_ in hp_t.idx) == sorted(chg) and (hp_t.kind == "basket_change").all())
    cbad = 0
    for bk in BOOKS:
        for fam in ("F1", "F3"):
            en = dd(bk, fam).end_nav.values
            for i_ in range(ND):
                cbad += int(abs(float(curves[f"{bk}|{fam}_{i_}"][-1]) / en[i_] - 1) > 1e-5)
    chk("draw_curves_20.8.npz: every F1 and F3 curve ends at the end NAV of its draws.csv row", cbad == 0, f"{cbad} differ")

    # 7b. whole-file consistency of the evidence
    ii = pd.read_csv(ev / "inputs.csv", dtype=str, keep_default_na=False)
    chk("inputs.csv (evidence) equals the page's input table row for row", [(r_.file, r_.through, r_.approved_row, r_.sha256[:16], r_.usable_from) for r_ in ii.itertuples()] == [(r_["file"], r_["through"], r_["approved_row"], r_["sha16"], r_["usable_from"]) for r_ in page["inputs"]])
    yrs_ = (dr.sessions - 1) / 252
    chk("draws.csv: cagr = end_nav^(252 / (sessions - 1)) - 1 on every row", bool((np.abs(dr.end_nav ** (1 / yrs_) - 1 - dr.cagr) <= 1e-9 * np.maximum(1, dr.cagr.abs())).all()))
    chk("draws.csv: no sleeve trades in any fixed50 row, the gold column is real there", bool((dr[dr.sleeve_mode == "fixed50"].sleeve_trades == 0).all() and (dr[dr.sleeve_mode == "fixed50"].gold_null == "real").all()))
    chk("stats.csv: cagr = end_nav^(252 / (sessions - 1)) - 1 on every row", bool((np.abs(st.end_nav ** (252 / (st.sessions - 1)) - 1 - st.cagr) <= 1e-9 * np.maximum(1, st.cagr.abs())).all()))
    cb2 = 0
    for bk in BOOKS:
        for fam in ("F1", "F3"):
            nd_ = dd(bk, fam)
            for i_ in range(ND):
                c_ = curves[f"{bk}|{fam}_{i_}"].astype(float)
                cb2 += int(abs(cagr(c_) - nd_.cagr.values[i_]) > 1e-5 or abs(mdd(c_) - nd_.max_dd.values[i_]) > 1e-5)
    chk("draw_curves_20.8.npz: the CAGR and maximum drawdown of every stored F1 and F3 curve equal its draws.csv row (float32 storage, 1e-5)", cb2 == 0, f"{cb2} differ")
    nvi = nav.assign(date=nav.date.dt.strftime("%Y-%m-%d")).set_index(["book", "cost_bps", "run", "date"]).nav
    got = nvi.reindex(pd.MultiIndex.from_arrays([tr.book, tr.cost_bps, tr.run, tr.date.astype(str)])).values
    chk(f"trades.csv: nav_close_after equals daily_nav.csv on the trade date, for all {len(tr):,} trades of every run and cost", bool((np.abs(got / tr.nav_close_after.values - 1) < 1e-9).all()))
    # positions after a trade: the same GOLDBEES and cash units at 0, 20.8 and 50 bps give the same fill (value / units) on a sleeve trade
    pg = po[po.run == "strategy"].pivot_table(index=["book", "cost_bps", "date"], columns="instrument", values="units", aggfunc="sum")
    sw = sl.merge(pg[["GOLDBEES", "LBES"]].reset_index(), on=["book", "cost_bps", "date"], how="left")
    sw = sw.assign(gfill=sw.gold_value_after / sw.GOLDBEES.where(sw.GOLDBEES > 0), cfill=sw.cash_value_after / sw.LBES.where(sw.LBES > 0))
    gg_ = sw.groupby(["book", "date", "kind"]).agg(gmax=("gfill", "max"), gmin=("gfill", "min"), cmax=("cfill", "max"), cmin=("cfill", "min"))
    chk("sleeve trades: the implied GOLDBEES fill and cash level (value after / units after) are the same at 0, 20.8 and 50 bps on each trade date", bool(((gg_.gmax / gg_.gmin - 1).abs().fillna(0) < 1e-9).all() and ((gg_.cmax / gg_.cmin - 1).abs().fillna(0) < 1e-9).all()) and len(sw) > 0)
    prev = po[po.run == "strategy"].pivot_table(index=["book", "cost_bps", "date"], columns="instrument", values="units", aggfunc="sum").reset_index().sort_values(["book", "cost_bps", "date"])
    for c_ in ("GOLDBEES", "LBES"):
        prev[c_ + "_prev"] = prev.groupby(["book", "cost_bps"])[c_].shift(1)
    rb2 = sl[sl.kind == "sleeve_rebalance"].merge(prev, on=["book", "cost_bps", "date"], how="left")
    chk("sleeve rebalances at every cost: GOLDBEES value / units and cash value / units are the same before and after the trade (same session's fill)",
        bool(((rb2.gold_value_before / rb2.GOLDBEES_prev) / (rb2.gold_value_after / rb2.GOLDBEES) - 1).abs().fillna(0).lt(1e-9).all() and ((rb2.cash_value_before / rb2.LBES_prev) / (rb2.cash_value_after / rb2.LBES) - 1).abs().fillna(0).lt(1e-9).all()) and len(rb2) > 0)
    pz = po[po.run == "strategy"]
    pz_s = pz[~pz.instrument.isin(["GOLDBEES", "LBES"])]
    cnt_s = pz_s.groupby(["book", "cost_bps", "date"]).size()
    nh_all = {(r_.book, str(r_.available_date)): int(r_.n_held) for r_ in bsk.itertuples()}
    bad_n = n_n = 0
    for r_ in tr[(tr.run == "strategy") & tr.kind.isin(["switch_in", "basket_change"])].itertuples():
        n_n += 1
        bad_n += int(int(cnt_s.get((r_.book, r_.cost_bps, str(r_.date)), 0)) != nh_all[(r_.book, str(r_.basket_eff))])
    chk(f"positions.csv: every entry and basket change (all costs) leaves as many stock lines as the basket in force lists ({n_n} trades)", n_n > 0 and bad_n == 0, f"{bad_n} differ")
    bad_x = [r_ for r_ in tr[(tr.run == "strategy") & tr.kind.isin(["switch_out", "sleeve_rebalance"])].itertuples() if int(cnt_s.get((r_.book, r_.cost_bps, str(r_.date)), 0)) != 0]
    chk("positions.csv: no stock line is held after an exit or a sleeve rebalance", not bad_x)
    z0 = pz_s[pz_s.cost_bps == 0.0].rename(columns={"units": "u0"}).drop(columns=["cost_bps", "run"])
    zm = pz_s[pz_s.cost_bps != 0.0].merge(z0, on=["book", "date", "instrument"], how="left")
    zm = zm.assign(ratio=zm.units / zm.u0)
    gr_ = zm.groupby(["book", "cost_bps", "date"]).ratio.agg(["max", "min", "count"])
    chk("positions.csv: on every entry and basket change the stock units at 20.8 and 50 bps are the 0-bps units times one factor (the same for every line of the trade)", len(gr_) > 0 and bool(gr_["min"].notna().all()) and bool(((gr_["max"] / gr_["min"] - 1).abs() < 1e-9).all()) and int(zm.u0.isna().sum()) == 0)
    # 6. every draw of every null, from the states; draws.csv columns recomputed
    nstate = nbad = 0
    for bk in BOOKS:
        for win in ("full", "r3"):
            for kind, typ in (("io", "N4.9"), ("io", "N4.10"), ("gold", "N4.9-g"), ("gold", "N4.10-g")):
                A = ST.get(f"{bk}|{win}|{kind}|{typ}")
                chk(f"states {bk}|{win}|{kind}|{typ} present", A is not None)
                if A is None:
                    continue
                r_ = real[(win, kind)][bk]
                ka, kb_ = len(lens(r_, 1)), len(lens(r_, 0))
                sa, sb = int(r_.sum()), int(len(r_) - r_.sum())
                chk(f"states {bk}|{win}|{kind}|{typ} shape (draws, weeks)", A.shape[0] == ND and A.shape[1] == len(r_), str(A.shape))
                bn = bounds_of(r_)
                ref_ = (sorted(lens(r_, 1)), sorted(lens(r_, 0)))
                for i in range(A.shape[0]):
                    la, lb = lens(A[i], 1), lens(A[i], 0)
                    ok = len(la) == ka and len(lb) == kb_ and sum(la) == sa and sum(lb) == sb and int(A[i, 0]) == int(r_[0])
                    if typ.startswith("N4.9"):
                        ok &= (sorted(la), sorted(lb)) == ref_
                    else:
                        ok &= min(la or [0]) >= bn[1][0] and max(la or [0]) <= bn[1][1] and min(lb or [0]) >= bn[0][0] and max(lb or [0]) <= bn[0][1]
                    nstate += 1
                    nbad += int(not ok)
    chk(f"every draw of every null holds its table ({nstate} draws)", nstate > 0 and nbad == 0, f"{nbad} bad")
    for bk in BOOKS:
        e = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
        tradable = [j for j in range(1, len(e)) if not pd.isna(e.trade_date[j])]

        def n_reb(s, g):
            return sum(1 for j in tradable if s[j - 1] == 0 and s[j] == 0 and g[j] != g[j - 1])
        for fam, kio, kg in (("F1", "io|N4.10", None), ("F2", "io|N4.9", None), ("F3", None, "gold|N4.10-g"), ("F4", None, "gold|N4.9-g")):
            A = ST[f"{bk}|full|{kio}"] if kio else None
            G = ST[f"{bk}|full|{kg}"] if kg else None
            exp = [n_reb(A[i].astype(int) if A is not None else rule[bk], G[i].astype(int) if G is not None else gold[bk]) for i in range(ND)]
            chk(f"{bk} {fam} sleeve_trades column equals the flips between OUT weeks, recomputed from the states", list(dd(bk, fam).sleeve_trades.values) == exp)
        for fam, mode in (("F1", "timed"), ("F1", "fixed50"), ("F2", "fixed50")):
            nd_ = dd(bk, fam, mode=mode)
            chk(f"{bk} {fam} ({mode}) invested weeks, BUY weeks and spell counts equal the rule's on every draw", bool((nd_.invested_weeks == int(rule[bk].sum())).all() and (nd_.g_buy_weeks == int(gold[bk].sum())).all()))
        jn_ = lambda a_, v_: "|".join(map(str, lens(a_, v_)))
        use_ = {"F1": ("io|N4.10", None), "F2": ("io|N4.9", None), "F3": (None, "gold|N4.10-g"), "F4": (None, "gold|N4.9-g"), "F5": ("io|N4.10", "gold|N4.10-g")}
        n_str = bad_str = 0
        for (win_, cash_, cost_, fam_, mode_), g_ in dr[dr.book == bk].groupby(["window", "cash", "cost_bps", "family", "sleeve_mode"]):
            ww_ = win_ if cash_ == "lbes" else "full"
            kio_, kg_ = use_[fam_]
            ri_, rg_ = RZ[f"{bk}|{ww_}|io"].astype(int), RZ[f"{bk}|{ww_}|gold"].astype(int)
            A_ = ST[f"{bk}|{ww_}|{kio_}"] if kio_ else None
            G_ = ST[f"{bk}|{ww_}|{kg_}"] if kg_ else None
            g_ = g_.sort_values("draw_id")
            ids_ = g_.draw_id.values
            e_in = [jn_(A_[i], 1) if A_ is not None else jn_(ri_, 1) for i in ids_]
            e_out = [jn_(A_[i], 0) if A_ is not None else jn_(ri_, 0) for i in ids_]
            e_gb = [jn_(G_[i], 1) if G_ is not None else jn_(rg_, 1) for i in ids_]
            e_gs = [jn_(G_[i], 0) if G_ is not None else jn_(rg_, 0) for i in ids_]
            n_str += len(g_)
            bad_str += int(list(g_.in_lengths.astype(str)) != e_in or list(g_.out_lengths.astype(str)) != e_out or list(g_.g_buy_lengths.astype(str)) != e_gb or list(g_.g_sell_lengths.astype(str)) != e_gs)
        chk(f"{bk}: the in/out and BUY/SELL length strings of every draws.csv row ({n_str} rows, every cost, window and cash) equal the saved states'", n_str > 0 and bad_str == 0, f"{bad_str} row groups differ")

    # 8. page text carries the numbers as printed
    for bk in BOOKS:
        pb = page["books"][bk]
        for txt in (f"{pb['F1_pct_cagr']:.1f}", f"{pb['F1_pct_dd']:.1f}", f"{pb['F2_pct_cagr']:.1f}", f"{pb['F2_pct_dd']:.1f}", f"{pb['F3_pct_cagr']:.1f}", f"{pb['F3_pct_dd']:.1f}", f"{pb['F4_pct_cagr']:.1f}", f"{pb['F4_pct_dd']:.1f}",
                    f"{pb['F1f_pct_cagr']:.1f}", f"{pb['F1f_pct_dd']:.1f}", f"{pb['F2f_pct_cagr']:.1f}", f"{pb['F2f_pct_dd']:.1f}",
                    f"{100 * pb['strategy_cagr']:.1f}%", f"{100 * pb['strategy_dd']:.1f}%", f"{100 * pb['strategy_fixed50_cagr']:.1f}%", f"{pb['F1_p_cagr']:.3f}", f"{pb['F3_p_cagr']:.3f}", f"{pb['holm_C1']:.3f}", f"{pb['holm_C3']:.3f}", f"{pb['holm_A1']:.3f}",
                    f"{pb['F1_r3_pct']:.1f}", f"{pb['F3_r3_pct']:.1f}", f"{pb['F1f_r3_pct']:.1f}", f"{100 * pb['hold_parent_cagr']:.1f}%"):
            chk(f"{bk} page prints {txt}", txt in html)
    chk("page names the pre-registration hash", page["prereg_sha256"][:12] in html)
    chk("page hash equals T11.md header", page["prereg_sha256"] in Path(a.doc).read_text(encoding="utf-8"))
    chk("page prints the window and the R3 start", page["start"] in html and page["end"] in html and page["r3_start"] in html)
    chk("page prints the draws count", f"{ND:,}" in html)
    for phr in ("80% when MAUc1 is BUY, 20% when SELL", "the first two are filled when the book holds the parent portfolio", "MAUc1-timed sleeve", "80/20 when the weekly MAUc1 gold supertrend is BUY", "Holm", "F3 and F4 keep the real switch",
                "Part A's rule", "plain 50/50 one", "Only C3 and C4 bear on the gold timing", "value ÷ units", "Hold the parent", "Hold the parent, 0 bps", "R2 is a null result by construction", "Amendments before the run",
                "There is no published-NAV comparator", "four real parents", "A basket change", "the basket in force", "Low power", "round trips of the in-or-out switch and", "sleeve trades (shared by the four books)", "A FAIL will mostly mean",
                "the minimum detectable edge (2.8 × the null's SD) is printed beside every FAIL", "Minimum detectable edge beside a FAIL", "The rebuilt parent NAV is not validated", "Nine manual Eikon exports", "Carried bars", "The Muhurat sessions",
                "Stock-days with a one-day move of 20% or more", "No hold-out exists", "T09 ran the same weekly decisions on the same weeks", "Before you read the numbers", "The outcome map of T11.md section 2", "Applies to this run",
                "R7", "price-quality sensitivity", "manual-export stocks"):
        chk(f"page carries the caption '{phr}'", phr in text, phr)
    chk("page no longer carries T09's proxy captions", not any(s_ in text for s_ in ("prox" "y portfolio", "Hold the prox" "y", "three raw indices", "Nifty 100 alone", "quarterly reset", "Quarterly reset", "band mix", "Band mixes", "MAUc1-based prox" "y")))
    chk("page no longer carries T08's published-NAV comparator", not any(s_ in text for s_ in ("Published NAV (D17)", "Hold the published")))
    # a MDE beside every FAIL: for each criterion the page prints the MDE of each book in the criteria table, exactly when the criterion fails
    for cr, (td_, tb_, stat_) in TAG_OF.items():
        mde_s = "; ".join(f"{bk} {page['books'][bk][f'{td_}_mde_{stat_}_pp']:.1f} pp" for bk in BOOKS)
        want = f"MDE (2.8 × null SD): {mde_s}"
        chk(f"criterion {cr}: the MDE is printed beside it exactly when it FAILs", (want in text) == (page["verdict"][cr] < 3), want)
    # the three comparisons printed up front: low power with the numbers
    chk("the power note states this run's round trips and sleeve trades", f"{page['books'][B0]['round_trips']} round trips of the in-or-out switch and {page['books'][B0]['sleeve_trades']} sleeve trades (shared by the four books)" in text)
    for bk in BOOKS:
        cv_ = page["caveats"][bk]
        chk(f"{bk} data caveats on the page: held export sessions, carried bars, flagged days equal the files", f"{bk} {cv_['held_export_sessions']:,}" in text and f"{bk} {cv_['carried_bars']}" in text and f"{bk} {cv_['flagged_days']}" in text)
        ab = au["books"].get(bk) or {}
        chk(f"{bk} carried bars and held stock-sessions without a bar equal audit.json", cv_["carried_bars"] == (ab.get("src_counts") or {}).get("carried_bars_in_window_all_stocks") and cv_["no_bar"] == ((ab.get("src_counts") or {}).get("held_stock_sessions_by_src") or {}).get("none"))
    chk("the stand-in sessions on the page equal audit.json's", page["stand_in"] == {"no_d18_bar": (au["books"][B0].get("calendar") or {}).get("d26_sessions_in_window_without_any_d18_bar"), "gold_no_own_bar": au["books"][B0].get("gold_sessions_without_own_bar"),
                                                                              "gold_no_mcx_range": au["books"][B0].get("gold_sessions_without_mcx_range_in_window")})
    # the R7 stock-days: rows of r7_flagged_days.csv recomputed (the 20% rule) and printed
    chk("r7_flagged_days.csv: every row has |close / prev_close - 1| >= 0.2, equal to ret, and a positive weight on t-1 or t", bool(((r7f.close / r7f.prev_close - 1 - r7f.ret).abs() < 1e-9).all() and (r7f.ret.abs() >= 0.2 - 1e-12).all() and ((r7f.w_prev > 0) | (r7f.w_cur > 0)).all()))
    chk("the page lists every flagged stock-day (book, date, stock)", all(f"<td>{H.escape(str(r_.book))}</td><td>{H.escape(str(r_.date))}</td><td>{H.escape(str(r_.stock))}</td>" in html for r_ in r7f.itertuples()) and len(page["r7"]["flagged"]) == len(r7f))
    # the outcome map: T11.md's table is on the page, and the rows that apply are recomputed from the verdict counts and T09's counts
    ocm = re.search(r"\*\*Outcome map:\*\*\n\n((?:\|.*\n)+)", docn)
    oc_lines = [[c_.strip() for c_ in l.strip().strip("|").split("|")] for l in ocm.group(1).strip().split("\n")]
    oc_rows = [r_ for r_ in oc_lines[1:] if not all(set(c_) <= set("-: ") for c_ in r_)]
    chk("T11.md has the 8-row outcome map and the page carries every cell", len(oc_rows) == 8 and all(re.sub(r"[*`]", "", c_) in text for r_ in oc_rows for c_ in r_))
    Vv = page["verdict"]
    gates_ok_ = bool(page["gates"]) and all(v_ == "PASS" for v_ in page["gates"].values()) and len(page["gates"]) == 6
    A_ok_, C_ok_, G_ok_ = Vv["A1"] >= 3 and Vv["A2"] >= 3, Vv["C1"] >= 3 and Vv["C2"] >= 3, Vv["C3"] >= 3 and Vv["C4"] >= 3
    t9c = page["t09_counts"]
    yn_ = lambda v_: "yes" if v_ else "no"
    dis_ = any((Vv[c_] >= 3) != (Vv[c_ + "_beside"] >= 3) for c_ in ("A1", "A2", "C1", "C2", "C3", "C4"))
    exp_app = [yn_(gates_ok_ and A_ok_ and C_ok_ and G_ok_), yn_(gates_ok_ and A_ok_ and C_ok_ and not G_ok_), yn_(gates_ok_ and A_ok_ != C_ok_), yn_(gates_ok_ and (not C_ok_) and G_ok_), yn_(gates_ok_ and not A_ok_ and not C_ok_ and not G_ok_),
               ("cannot be assessed (T09's evidence not found)" if t9c is None else yn_(gates_ok_ and ((A_ok_ and not (t9c["A1"] >= 3 and t9c["A2"] >= 3)) or (C_ok_ and not (t9c["C1"] >= 3 and t9c["C2"] >= 3))))), yn_(gates_ok_ and dis_), yn_(not gates_ok_)]
    chk("outcome-map rows that apply to this run", page["outcome_rows"] == exp_app, f"{page['outcome_rows']} vs {exp_app}")
    mt_ = re.search(r'<table class="wrap"><thead><tr><th>Pattern</th><th>Conclusion</th><th>Applies to this run</th></tr></thead><tbody>(.*?)</tbody>', html, re.S)
    cells3 = re.findall(r"<tr><td>.*?</td><td>.*?</td><td><b>(.*?)</b></td></tr>", mt_.group(1), re.S) if mt_ else []
    chk("the outcome-map table on the page carries the answer, row by row", [H.unescape(c_) for c_ in cells3] == exp_app, f"{cells3} vs {exp_app}")
    chk("the page's gate verdict is six PASS", gates_ok_ == bool(page["gates"]))
    figs = re.findall(r"<figure.*?</figure>", html, re.S)
    chart_figs = [f_ for f_ in figs if 'class="chart lc"' in f_ or 'id="regime-svg"' in f_]
    chk("every growth chart (4 rebuilt NAV charts, 4 comparator charts, the regime chart) is a figure carrying the caption", len(chart_figs) == 2 * len(BOOKS) + 1 and all(f'<div class="cap rebuilt-cap"><b>Rebuilt NAV:</b> {H.escape(CAPTION)}.</div>' in f_ for f_ in chart_figs), f"{len(chart_figs)} figures")
    rb_figs = [f_ for f_ in chart_figs if 'data-book="rebuilt|' in f_]
    chk("one rebuilt-NAV chart per parent", len(rb_figs) == len(BOOKS) and all(f'data-book="rebuilt|{bk}"' in html for bk in BOOKS))
    docn = Path(a.doc).read_text(encoding="utf-8").replace("\r\n", "\n")
    for marker in ("**Null table, in-or-out nulls", "**Null table, gold nulls"):
        i = docn.index(marker)
        started, rows = False, []
        for l in docn[i:].split("\n")[1:]:
            if l.startswith("|"):
                started = True
                cells = [c.strip() for c in l.strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
            elif started:
                break
        chk(f"T11.md table '{marker}' parsed", len(rows) >= 8)
        for r_ in rows:
            for c in r_:
                chk(f"page carries the table cell '{c[:40]}'", re.sub(r"[*`]", "", c) in text, c[:60])
    if "### Amendments before the run" in docn:
        am_ = docn[docn.index("### Amendments before the run"):docn.index("\n## 5. Findings")]
        items = [re.sub(r"^\d+\.\s*", "", l.strip()) for l in am_.split("\n") if re.match(r"^\d+\.", l.strip())]
        chk("T11.md has its amendment items and the page carries each of them", len(items) >= 1 and all(re.sub(r"[*`]", "", re.sub(r"\s+", " ", it))[:80] in re.sub(r"\s+", " ", text) for it in items))
    else:
        chk("T11.md has no amendments block: the page says so", "No amendment to the frozen text is recorded in T11.md at the time of this build." in text)

    # 8a2. the gap section (hold the parent against Part B and Part A at 0 bps): its table equals daily_nav.csv, its images are the plot files byte for byte
    mg_ = re.search(r'<h2 id="gap">.*?(?=<h2 id="perbook">)', html, re.S)
    chk("the gap section exists, before the per-book comparators", mg_ is not None)
    if mg_ is not None:
        g_html = mg_.group(0)
        exp_g = []
        for lab_, run_ in (("Part B (timed sleeve)", "strategy"), ("Part A (50/50 sleeve)", "strategy_fixed50")):
            for bk in BOOKS:
                qp_ = nav[(nav.book == bk) & (nav.cost_bps == 0.0) & (nav.run == "hold_parent")].sort_values("date")
                qr_ = nav[(nav.book == bk) & (nav.cost_bps == 0.0) & (nav.run == run_)].sort_values("date")
                assert list(qp_.date) == list(qr_.date)
                ip_, ir_ = 100 * qp_.nav.values, 100 * qr_.nav.values
                gp_ = ip_ - ir_
                exp_g.append([lab_, bk, f"{ip_[-1]:.1f}", f"{ir_[-1]:.1f}", f"{gp_[-1]:+.1f}", f"{gp_.max():+.1f}", str(qp_.date.iloc[int(gp_.argmax())].date())])
        rows_g = re.findall(r"<tr>(.*?)</tr>", re.search(r"<tbody>(.*?)</tbody>", g_html, re.S).group(1), re.S)
        got_g = [[H.unescape(c_) for c_ in re.findall(r"<td>(.*?)</td>", r_, re.S)] for r_ in rows_g]
        chk("gap table: every row (end parent index, end rule index, end gap, largest gap and its date, at 0 bps) equals daily_nav.csv", got_g == exp_g, f"{got_g[:2]} vs {exp_g[:2]}")
        plots_ = ev.parent / "plots"
        want_ = [plots_ / "parent_vs_partb_0bps.png", plots_ / "parent_vs_parta_0bps.png"]
        imgs_ = [base64.b64decode(s_) for s_ in re.findall(r'src="data:image/png;base64,([^"]+)"', g_html)]
        chk("the two embedded gap images are evidence/plots/parent_vs_partb_0bps.png and parent_vs_parta_0bps.png, byte for byte", all(p_.exists() for p_ in want_) and imgs_ == [p_.read_bytes() for p_ in want_])
        chk("the gap figures name their window, the formula and the caption", g_html.count('class="cap rebuilt-cap"') == 2 and "index of parent − index of Part B" in g_html and "index of parent − index of Part A" in g_html and f"{nav.date.min().date()} → {nav.date.max().date()}" in g_html)

    # 8b. printed tables: exact rows, rebuilt from the page's own data
    pcf = lambda x_, d_=1: f"{100 * x_:.{d_}f}%"
    LABS = {"strategy": "Rule, MAUc1-timed sleeve (Part B)", "strategy_fixed50": "Rule, 50/50 sleeve (Part A)", "hold_parent": "Hold the parent", "constant_mix": "Constant mix, 50/50 non-stock share",
            "constant_mix_timed": "Constant mix, MAUc1-timed non-stock share", "sleeve_only": "50/50 GOLDBEES + cash", "sleeve_only_timed": "MAUc1-timed GOLDBEES + cash"}
    tr_row = lambda cells: "<tr>" + "".join(f"<td>{c_}</td>" for c_ in cells) + "</tr>"
    for bk in BOOKS:
        x = page["books"][bk]
        ans = [H.escape(bk)] + [y_ for cr, _s, td_, tb_ in CRIT for y_ in (f"{x[td_ + '_pct_' + ('dd' if _s == 'max_dd' else 'cagr')]:.1f}", f"{x['holm_' + cr]:.3f}")]
        chk(f"{bk} answer-table row is on the page exactly as the data give it", tr_row(ans) in html)
        for t1, t2, rk, c1, c2 in (("F1f", "F2f", "strategy_fixed50", "A1", "A2"), ("F1", "F2", "strategy", "C1", "C2")):
            row = [H.escape(bk), pcf(x["hold_parent_cagr"]), pcf(x[f"{rk}_cagr"]), pcf(x[f"{t1}_median_cagr"]), f"{100 * (x[f'{rk}_cagr'] - x[f'{t1}_median_cagr']):+.1f} pp", f"<b>{x[f'{t1}_pct_cagr']:.1f}</b>", f"{x[f'{t1}_p_cagr']:.3f}", f"{x['holm_' + c1]:.3f}",
                   pcf(x[f"{t2}_median_cagr"]), f"<b>{x[f'{t2}_pct_cagr']:.1f}</b>", f"{x[f'{t2}_p_cagr']:.3f}", pcf(x["hold_parent_dd"]), pcf(x[f"{rk}_dd"]), pcf(x[f"{t1}_median_dd"]), f"<b>{x[f'{t1}_pct_dd']:.1f}</b>", f"{x[f'{t1}_p_dd']:.3f}",
                   f"{x['holm_' + c2]:.3f}", pcf(x[f"{t2}_median_dd"]), f"<b>{x[f'{t2}_pct_dd']:.1f}</b>", f"{x[f'{t2}_p_dd']:.3f}"]
            chk(f"{bk} headline row {c1}/{c2} is on the page exactly as the data give it", tr_row(row) in html)
        row = [H.escape(bk), pcf(x["strategy_cagr"]), pcf(x["F3_median_cagr"]), f"{100 * (x['strategy_cagr'] - x['F3_median_cagr']):+.1f} pp", f"<b>{x['F3_pct_cagr']:.1f}</b>", f"{x['F3_p_cagr']:.3f}", f"{x['holm_C3']:.3f}", pcf(x["F4_median_cagr"]),
               f"<b>{x['F4_pct_cagr']:.1f}</b>", f"{x['F4_p_cagr']:.3f}", pcf(x["strategy_dd"]), pcf(x["F3_median_dd"]), f"<b>{x['F3_pct_dd']:.1f}</b>", f"{x['F3_p_dd']:.3f}", f"{x['holm_C4']:.3f}", pcf(x["F4_median_dd"]), f"<b>{x['F4_pct_dd']:.1f}</b>", f"{x['F4_p_dd']:.3f}"]
        chk(f"{bk} headline row C3/C4 is on the page exactly as the data give it", tr_row(row) in html)
        for kind in KINDS:
            row = [H.escape(bk) if kind == "strategy" else "", LABS[kind]] + [y_ for c_ in (0.0, 20.8, 50.0) for y_ in (pcf(x[f"{kind}_cagr_{c_:g}"]), pcf(x[f"{kind}_dd_{c_:g}"]))]
            chk(f"{bk} cost-table row {kind} is on the page exactly as the data give it", tr_row(row) in html)

    # 9. the verifier and the gates
    vj = ev / "verify_t11.json"
    chk("verify_t11.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0, "verify_t11.json does not say passed")
        chk("verifier compared rows (more than 100,000 on a full 2,000-draw run, more than 1,000 on a short one)", v.get("gate_compared", 0) > (100000 if ND >= 2000 else 1000), str(v.get("gate_compared")))
        chk("verifier caught the corrupted copy", bool(v.get("selftest", {}).get("detected")))
    lp = logdir / "analysis.log"
    chk("analysis.log exists", lp.exists())
    if lp.exists():
        mg_ = re.search(r"^Gates: (\{.*\}) ->(.*)$", lp.read_text(encoding="utf-8"), re.M)
        chk("analysis.log has a Gates line", mg_ is not None)
        if mg_:
            g = ast.literal_eval(mg_.group(1))
            chk("all six gates pass in analysis.log", sorted(g) == ["V1", "V2", "V3", "V4", "V5", "V6"] and all(x == "PASS" for x in g.values()) and "ALL PASS" in mg_.group(2), mg_.group(0))
            chk("page's gates equal analysis.log's", page["gates"] == g)

    # 10a. regime chart hover
    bdd = page["best_draw"]
    bk = bdd["book"]
    q = lambda kind, c: nav[(nav.book == bk) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").reset_index(drop=True)
    rq, pq_ = q("strategy", 20.8), q("hold_parent", 0.0)
    n10 = dd(bk, "F1")
    chk("regime section: draw is the highest-CAGR F1 draw of the book", close(float(n10[n10.draw_id == bdd["draw_id"]].cagr.iloc[0]), float(n10.cagr.max()), 1e-15) and close(bdd["cagr"], float(n10.cagr.max())))
    curve = curves[f"{bk}|F1_{bdd['draw_id']}"].astype(float)
    nses = len(rq)
    chk("hover: one entry per session", all(len(hv[k_]) == nses for k_ in ("dates", "rule", "draw", "parent", "rs", "ds", "g", "gw", "tip")))
    chk("hover: dates are the NAV calendar", hv["dates"] == [d.strftime("%Y-%m-%d (%a)") for d in rq.date])
    chk("hover: rule NAV", np.abs(np.array(hv["rule"]) - rq.nav.values).max() < 6e-5)
    chk("hover: parent NAV (hold, 0 bps)", np.abs(np.array(hv["parent"]) - pq_.nav.values).max() < 6e-5)
    chk("hover: draw NAV is the stored curve of the page's draw", np.abs(np.array(hv["draw"]) - curve).max() < 6e-5)
    chk("curve ends at the draw's end NAV", close(float(curve[-1]), bdd["end_nav"], 1e-5))
    dcb = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
    r_, d_ = rule[bk], ST[f"{bk}|full|io|N4.10"][bdd["draw_id"]].astype(int)
    first = np.array([0] + [nses - 1 if pd.isna(t) else int(rq.index[rq.date == pd.Timestamp(t)][0]) for t in dcb.trade_date.iloc[1:]])
    exp_r, exp_d, exp_g, exp_w = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses)
    for j in range(len(d_)):
        end = first[j + 1] if j + 1 < len(d_) else nses - 1
        exp_r[first[j]:end], exp_d[first[j]:end] = r_[j], d_[j]
        exp_g[first[j]:end], exp_w[first[j]:end] = gold[bk][j], 0.8 if gold[bk][j] else 0.2
    exp_r[-1], exp_d[-1], exp_g[-1], exp_w[-1] = exp_r[-2], exp_d[-2], exp_g[-2], exp_w[-2]
    chk("hover: the rule's state each session", (np.array(hv["rs"]) == exp_r).all())
    chk("hover: the draw's state each session", (np.array(hv["ds"]) == exp_d).all())
    chk("hover: the MAUc1 signal each session (real, from the decisions)", (np.array(hv["g"]) == exp_g).all())
    chk("hover: the sleeve's GOLDBEES target weight each session", np.abs(np.array(hv["gw"]) - exp_w).max() < 1e-4)
    chk("hover: every session points at a stretch text that names its start and end date", all(0 <= i < len(hv["tips"]) for i in hv["tip"]) and all(isinstance(t, str) and re.match(r"\d{4}-\d{2}-\d{2} → \d{4}-\d{2}-\d{2}, ", t) for t in hv["tips"]))
    chk("regime chart has one overlay and one tooltip", html.count('id="regime-ov"') == 1 and html.count('id="regime-tip"') == 1)
    chk("regime chart has the six strips' labels", all(f">{lab}</text>" in html for lab in ("Rule", "They differ", "MAUc1 BUY", "Rule gold wt")))
    chk("regime table: weeks by what the two did", (bdd["weeks_both_in"], bdd["weeks_both_out"], bdd["weeks_draw_only"], bdd["weeks_rule_only"]) ==
        (int(((r_ == 1) & (d_ == 1)).sum()), int(((r_ == 0) & (d_ == 0)).sum()), int(((r_ == 0) & (d_ == 1)).sum()), int(((r_ == 1) & (d_ == 0)).sum())))
    chk("held: weeks invested equal and as printed", int(r_.sum()) == int(d_.sum()) == bdd["weeks_invested_rule"] == bdd["weeks_invested_draw"])
    chk("held: spell counts", (len(lens(r_, 1)), len(lens(r_, 0))) == (len(lens(d_, 1)), len(lens(d_, 0))) == (bdd["in_spells"], bdd["out_spells"]))
    chk("F1 draw: lengths within the bounds and as printed", bdd["draw_in"] == lens(d_, 1) and bdd["draw_out"] == lens(d_, 0) and min(lens(d_, 1)) >= bi[1][0] and max(lens(d_, 1)) <= bi[1][1] and min(lens(d_, 0)) >= bi[0][0] and max(lens(d_, 0)) <= bi[0][1])
    chk("held: entries and exits", (int(((r_[1:] == 1) & (r_[:-1] == 0)).sum()) + int(r_[0] == 1), int(((r_[1:] == 0) & (r_[:-1] == 1)).sum())) == (int(((d_[1:] == 1) & (d_[:-1] == 0)).sum()) + int(d_[0] == 1), int(((d_[1:] == 0) & (d_[:-1] == 1)).sum())) == (bdd["entries"], bdd["exits"]))
    chk("held: first state", r_[0] == d_[0])
    chk("sessions invested, rule and draw, as printed", (int(exp_r[:-1].sum()), int(exp_d[:-1].sum()), nses - 1) == (bdd["sessions_invested_rule"], bdd["sessions_invested_draw"], bdd["sessions_span"]))
    gdd = page["best_gold_draw"]
    ng = dd(bk, "F3")
    chk("best gold draw is the highest-CAGR F3 draw of the book", gdd["book"] == bk and close(float(ng[ng.draw_id == gdd["draw_id"]].cagr.iloc[0]), float(ng.cagr.max()), 1e-15) and close(gdd["cagr"], float(ng.cagr.max())) and close(gdd["end_nav"], float(ng[ng.draw_id == gdd["draw_id"]].end_nav.iloc[0])))
    gx = ST[f"{bk}|full|gold|N4.10-g"][gdd["draw_id"]].astype(int)
    tradable = [j for j in range(1, len(dcb)) if not pd.isna(dcb.trade_date[j])]
    fo = lambda g_: sum(1 for j in tradable if r_[j - 1] == 0 and r_[j] == 0 and g_[j] != g_[j - 1])
    chk("best gold draw: held and randomised dimensions as printed", (gdd["buy_weeks_real"], gdd["buy_weeks_draw"]) == (int(gold[bk].sum()), int(gx.sum())) and gdd["spells_real"] == [len(lens(gold[bk], 1)), len(lens(gold[bk], 0))]
        and gdd["spells_draw"] == [len(lens(gx, 1)), len(lens(gx, 0))] and gdd["draw_buy"] == lens(gx, 1) and gdd["draw_sell"] == lens(gx, 0) and gdd["flips_out_real"] == fo(gold[bk]) and gdd["flips_out_draw"] == fo(gx) == gdd["sleeve_trades_draw"]
        and min(lens(gx, 1)) >= bg[1][0] and max(lens(gx, 1)) <= bg[1][1] and min(lens(gx, 0)) >= bg[0][0] and max(lens(gx, 0)) <= bg[0][1] and gx[0] == gold[bk][0])

    # 10b. per-book growth-of-1 charts (the comparators) and the rebuilt parent NAV charts
    chk("line hover: one entry per book and one rebuilt-NAV entry per book", sorted(lh) == sorted(BOOKS + [f"rebuilt|{b}" for b in BOOKS]))
    chk("line charts: one hover overlay and one tooltip per chart", html.count('class="lc-ov"') == 2 * len(BOOKS) and html.count('<div class="tip" hidden></div>') == 2 * len(BOOKS))
    for b in BOOKS:
        cur = {k_: nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == k_)].sort_values("date").reset_index(drop=True) for k_ in KINDS}
        cl = cur["strategy"].date
        sel = np.unique(np.append(np.arange(0, len(cl), 5), len(cl) - 1))
        h = lh[b]
        chk(f"line hover {b}: series are the seven curves, in legend order", [s["k"] for s in h["series"]] == list(cur))
        chk(f"line hover {b}: plotted sessions", h["n"] == len(sel) and len(h["dates"]) == len(sel))
        chk(f"line hover {b}: dates are the NAV calendar", h["dates"] == [cl[i].strftime("%Y-%m-%d (%a)") for i in sel])
        for s in h["series"]:
            chk(f"line hover {b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - cur[s["k"]].nav.values[sel]).max() < 6e-5)
        pq = pnd[pnd.book == b].sort_values("date").reset_index(drop=True)
        h = lh[f"rebuilt|{b}"]
        chk(f"rebuilt-NAV hover {b}: the four series, in file order", [s["k"] for s in h["series"]] == [v_[0] for v_ in RB.values()] and [s["label"] for s in h["series"]] == ["Hold the parent, 0 bps", "Hold the parent, 20.8 bps", "Part A (50/50 sleeve), 20.8 bps", "Part B (timed sleeve), 20.8 bps"])
        chk(f"rebuilt-NAV hover {b}: plotted sessions and dates are the file's", h["n"] == len(sel) and h["dates"] == [pq.date[i].strftime("%Y-%m-%d (%a)") for i in sel])
        for s, col_ in zip(h["series"], RB):
            chk(f"rebuilt-NAV hover {b}: {s['k']} values are {col_} of {PARENT_NAV}.csv", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - pq[col_].values[sel]).max() < 6e-5)
        chk(f"rebuilt-NAV chart {b}: the figure's text names its start and end date", f"the rebuilt parent NAV, growth of 1 from {pq.date.iloc[0].date()} to {pq.date.iloc[-1].date()}" in text)

    # 10c. bar charts
    want = {f"hist|{b}|{t}|{w}" for b in BOOKS for t in ("io50", "io", "gold") for w in ("cagr", "dd")} | {f"len|{b}|{s}" for b in BOOKS for s in ("in", "out", "buy", "sell")} | {"sampler|first", "sampler|first_g"}
    chk("bars-data holds exactly the expected charts", set(bd) == want, f"{sorted(set(bd) ^ want)}")
    chk("bar charts: one hover overlay and one tooltip each", html.count('class="bc-ov"') == len(want) and html.count('<div class="tip wrap" hidden></div>') == len(want))
    fm = lambda v: f"{100 * v:.1f}%"
    for b in BOOKS:
        for tim, td, tb in (("io50", "F1f", "F2f"), ("io", "F1", "F2"), ("gold", "F3", "F4")):
            fd, md_, rk = TAGS[td]
            fb = TAGS[tb][0]
            s_rule = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == rk)].iloc[0]
            dd_d, dd_b = dd(b, fd, mode=md_), dd(b, fb, mode=md_)
            for what, col, mark in (("cagr", "cagr", float(s_rule.cagr)), ("dd", "max_dd", float(s_rule.max_dd))):
                h = bd[f"hist|{b}|{tim}|{what}"]
                ad, ab = dd_d[col].values, dd_b[col].values
                lo_, hi_ = float(min(ad.min(), ab.min(), mark)), float(max(ad.max(), ab.max(), mark))
                edges = np.linspace(lo_ - (hi_ - lo_) * 0.04, hi_ + (hi_ - lo_) * 0.04, 33)
                cd, cb = np.histogram(ad, bins=edges)[0], np.histogram(ab, bins=edges)[0]
                nm_ = f"hist {b} {tim} {what}"
                chk(f"{nm_}: edges", len(h["edges"]) == 33 and np.abs(np.array(h["edges"]) - edges).max() < 1e-7)
                sv = {x["k"]: x for x in h["series"]}
                chk(f"{nm_}: counts of both nulls", sv[fd]["v"] == [int(x) for x in cd] and sv[fb]["v"] == [int(x) for x in cb] and sv[fd]["n"] == sv[fb]["n"] == ND and sum(sv[fd]["v"]) == ND == sum(sv[fb]["v"]))
                mk = {m["label"]: m for m in h["marks"]}
                chk(f"{nm_}: marks are the rule and each null's median", close(mk["The rule"]["x"], mark, 1e-7) and close(mk[f"{fd} median"]["x"], float(np.median(ad)), 1e-7) and close(mk[f"{fb} median"]["x"], float(np.median(ab)), 1e-7))
                chk(f"{nm_}: the rule's percentiles in the tooltip", mk["The rule"]["txt"] == f"percentile {pctl(mark, ad)[0]:.1f} vs {fd}, {pctl(mark, ab)[0]:.1f} vs {fb}")
                chk(f"{nm_}: bin labels", h["binlab"] == [f"{fm(edges[i])} to {fm(edges[i + 1])}" for i in range(32)])
                chk(f"{nm_}: every tooltip names the start and end date of the window", h["extra"] == [f"{'After-cost CAGR' if what == 'cagr' else 'Maximum drawdown'} of {ND:,} draws and of the rule, {T0.date()} → {END.date()}, 20.8 bps"] * 32)
        for tim, fd, fb, kd, kb_, parts in (("io", "F1", "F2", "io|N4.10", "io|N4.9", (("in", 1, rin), ("out", 0, rout))), ("gold", "F3", "F4", "gold|N4.10-g", "gold|N4.9-g", (("buy", 1, gbuy), ("sell", 0, gsell)))):
            Ad, Ab = ST[f"{b}|full|{kd}"], ST[f"{b}|full|{kb_}"]
            for sx, v_, rl_all in parts:
                lo_, hi = (bi if tim == "io" else bg)[v_]
                h = bd[f"len|{b}|{sx}"]
                ld = np.array([x for i in range(Ad.shape[0]) for x in lens(Ad[i], v_)])
                lb = np.array([x for i in range(Ab.shape[0]) for x in lens(Ab[i], v_)])
                e_ = np.arange(lo_, hi + 2) - 0.5
                sv = {x["k"]: x for x in h["series"]}
                nm_ = f"length chart {b} {sx}"
                chk(f"{nm_}: edges", np.abs(np.array(h["edges"]) - e_).max() < 1e-9)
                chk(f"{nm_}: counts", sv[fd]["v"] == [int(x) for x in np.histogram(ld, bins=e_)[0]] and sv[fb]["v"] == [int(x) for x in np.histogram(lb, bins=e_)[0]] and sv[fd]["n"] == len(ld) and sv[fb]["n"] == len(lb))
                rl = rl_all[b]
                chk(f"{nm_}: the shuffle's spikes are the real series' own lengths", sv[fb]["v"] == [ND * rl.count(x) for x in range(lo_, hi + 1)])
                chk(f"{nm_}: tooltip notes the real series' spells", h["extra"] == [(f"The real series has {rl.count(x)} {sx}-spell(s) of exactly this length; " if rl.count(x) else "") + f"spells of {ND:,} draws, full window {T0.date()} → {END.date()}" for x in range(lo_, hi + 1)])
                chk(f"{nm_}: bin labels", h["binlab"] == [f"{x} weeks" for x in range(lo_, hi + 1)])
    for did, kk, SSx, bn_, mark_x, key in (("sampler|first", kin, Sin, bi[1], ex["steps"][0]["x"], "sampler_first"), ("sampler|first_g", kb, Sb, bg[1], ex["steps_g"][0]["x"], "sampler_first_g")):
        h = bd[did]
        chk(f"{did}: bars are the first-step weights", h["series"][0]["v"] == page[key]["weights"] and h["series"][0]["n"] == sum(page[key]["weights"]) and h["marks"][0]["x"] == float(mark_x))
    for did, h in bd.items():
        m = re.search(r'<svg[^>]*data-id="' + re.escape(did) + r'"[^>]*>(.*?)</svg>', html, re.S)
        chk(f"svg for {did} exists", m is not None)
        if not m:
            continue
        rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9a-f]{6})" opacity="([\d.]+)"/>', m.group(1))
        ymaxax = h["ymax"]
        ytop = max(max(s["v"]) for s in h["series"])
        chk(f"{did}: y axis maximum is the top tick (or the tallest bar)", close(ymaxax, max(nice_ticks_max(ytop), ytop), 1e-9), f"{ymaxax} vs {ytop}")
        exp = [(s["col"], i, c) for s in h["series"] for i, c in enumerate(s["v"]) if c > 0]
        chk(f"{did}: one bar rectangle per non-empty bin and series ({len(exp)})", len(rects) == len(exp), f"{len(rects)} vs {len(exp)}")
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okb = True
        for (col, i, c), (rx, ry, rw, rh, rc, ro) in zip(exp, rects):
            xl = h["L"] + pw * (h["edges"][i] - h["x0"]) / (h["x1"] - h["x0"]) + 0.4
            hh = ph * c / ymaxax
            okb &= (rc == col and abs(float(rx) - xl) < 0.06 and abs(float(rh) - hh) < 0.06 and abs(float(ry) + float(rh) - (h["h"] - h["B"])) < 0.12)
        chk(f"{did}: every bar's position and height follow the arrays", okb)

    print(f"check_page: {n} checks, {len(fails)} failures")
    for f in fails[:40]:
        print("FAIL", f)
    sys.exit(0 if (n > 0 and not fails) else 1)


def qs_set(cal_all, qs):
    return set(cal_all[q_] for q_ in qs)


if __name__ == "__main__":
    main()
