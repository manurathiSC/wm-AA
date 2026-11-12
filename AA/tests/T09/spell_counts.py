"""T09 Step 1: spell counts of the three-index switch AND of the MAUc1 gold signal on the pre-2019 window. Counts only: no price, NAV or return is read.

    python tests/T09/spell_counts.py        writes tests/T09/logs/step_1_spell_counts.json and prints a table

Reads only APPROVED rows of data/APPROVED_DATA.md: the NSE calendar (D26), the index Masters (D03; the Smallcap 100 rows are sliced to the window start the
moment the file is read, and `approved_data.guard_window` is called, standing rule 7) and Master_MAUc1.xlsx (D24b, the gold signal; its weekly CSV is the cross-check).
Decision rule as T06/T08: T0, then the last D26 session of every later ISO week up to the window end; IN iff the latest Master row on or before the date is BUY
in all three indices; g = SIGN of the latest MAUc1 Master row on or before the date.
Bounds (new, plan section 'Bounds'): per state of every series, lo = min(2, shortest actual spell) and hi = longest actual spell, taken from the actual series.
The proxy weights are typed constants (provenance: tests/T07/logs/step_1_counts.json, mean_band_share_all_weeks, full window, renormalised); this script checks them.
Used to fix the pre-registration (section 2) before any engine code exists.
"""
import hashlib
import json
import sys
from math import comb
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import approved_data as ad  # noqa: E402

T0 = pd.Timestamp("2011-11-25")
END = pd.Timestamp("2019-01-02")
R3_START = pd.Timestamp("2012-01-02")
SC_FIRST_READ = T0                      # the Smallcap 100 signal rows read start here (D03 restriction)
DIR = "Historical Data/"
FILES = {
    "cal": DIR + "extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv",
    "Nifty100": DIR + "extended_2026-10-30/Master/Master_Nifty100.xlsx",
    "MC100": DIR + "extended_2026-10-30/Master/Master_MC100.xlsx",
    "SC100": DIR + "extended_2026-10-30/Master/Master_SC100.xlsx",
    "gold": DIR + "extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx",
    "gold_weekly": DIR + "extended_2026-11-12/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv",
}
SEEDS = {"N4.9": [12, 3], "N4.10": [12, 6], "N4.9-g": [12, 11, 3], "N4.10-g": [12, 11, 6]}   # + [draw_id]
WEIGHTS = {  # (Large = Nifty 100, Mid = Midcap 100, Small and below = Smallcap 100); sum 1 (T07 step_1_counts.json, full window, all weeks)
    "SCMO_0003": (0.09626177, 0.19679459, 0.70694364),
    "SCMO_0007": (0.04799800, 0.17801859, 0.77398341),
    "SCMO_0010": (0.26590767, 0.21230665, 0.52178568),
    "SCMO_0029": (0.31294405, 0.28378774, 0.40326821),
}
T07_COUNTS = AA / "tests" / "T07" / "logs" / "step_1_counts.json"


def spells(s):
    runs, cur, c = [], int(s[0]), 0
    for v in s:
        if int(v) == cur:
            c += 1
        else:
            runs.append((cur, c)); cur, c = int(v), 1
    runs.append((cur, c))
    return runs


def n_ways(k, S, lo, hi):
    """Number of ordered k-tuples of integers in [lo, hi] summing to S (inclusion-exclusion)."""
    return sum((-1) ** j * comb(k, j) * comb(S - k * lo - j * (hi - lo + 1) + k - 1, k - 1)
               for j in range(k + 1) if S - k * lo - j * (hi - lo + 1) >= 0)


def asof(series, d):
    i = series.index.searchsorted(d, side="right") - 1
    assert i >= 0, f"no row on or before {d.date()}"
    return series.iloc[i]


def table(runs):
    """Per state: k, S, shortest, longest, the bounds lo = min(2, shortest), hi = longest, feasibility lo*k <= S <= hi*k, exact tuple count."""
    out = {}
    for state, label in ((1, "in"), (0, "out")):
        ls = [c for v, c in runs if v == state]
        lo, hi = min(2, min(ls)), max(ls)
        ok = lo * len(ls) <= sum(ls) <= hi * len(ls)
        out[label] = {"k": len(ls), "S": sum(ls), "lengths": ls, "shortest": min(ls), "longest": hi, "lo": lo, "hi": hi,
                      "feasible": bool(ok), "rule_inside_bounds": all(lo <= L <= hi for L in ls), "n_ways": str(n_ways(len(ls), sum(ls), lo, hi))}
    return out


def window(cal_all, sig, gsig, gweekly, start):
    cal = cal_all[(cal_all >= start) & (cal_all <= END)]
    assert cal[0] == start and cal[-1] == END, (cal[0], cal[-1])
    wk = pd.Series(cal, index=cal)
    iso = cal.isocalendar()
    last = sorted(wk.groupby([iso.year.values, iso.week.values]).max().values)
    dates = [cal[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > cal[0]]
    st, g = [], []
    for d in dates:
        ok = 1
        for s in sig.values():
            ok &= int(asof(s, d) == "BUY")
        st.append(ok)
        g.append(int(asof(gsig, d) == "BUY"))
    r, rg = spells(st), spells(g)
    ins, outs = [c for v, c in r if v == 1], [c for v, c in r if v == 0]
    buys, sells = [c for v, c in rg if v == 1], [c for v, c in rg if v == 0]
    flips = [j for j in range(1, len(g)) if g[j] != g[j - 1]]
    flips_out = [j for j in flips if st[j] == 0 and st[j - 1] == 0]
    flips_exit = [j for j in flips if st[j] == 0 and st[j - 1] == 1]
    flips_in = [j for j in flips if st[j] == 1]
    touching = sum(1 for _ in _spells_touching_out(g, st))
    rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "sessions": len(cal), "weeks": len(st), "first_state": st[0], "last_state": st[-1],
           "in_spells": len(ins), "out_spells": len(outs), "S_in": sum(ins), "S_out": sum(outs), "in_lengths": ins, "out_lengths": outs,
           "weeks_in": sum(ins), "weeks_out": sum(outs), "round_trips": min(len(ins), len(outs)),
           "g_first_state": g[0], "g_last_state": g[-1], "g_buy_spells": len(buys), "g_sell_spells": len(sells), "g_S_buy": sum(buys), "g_S_sell": sum(sells),
           "g_buy_lengths": buys, "g_sell_lengths": sells, "g_shortest": min(buys + sells),
           "g_flips": len(flips), "g_flips_while_out_both_sides": len(flips_out), "g_flips_on_an_exit_decision": len(flips_exit), "g_flips_while_in": len(flips_in),
           "g_flip_dates_while_out": [str(dates[j].date()) for j in flips_out], "g_spells_with_an_out_week": touching,
           "g_weeks_buy_while_out": sum(1 for j in range(len(g)) if g[j] == 1 and st[j] == 0),
           "g_weeks_sell_while_out": sum(1 for j in range(len(g)) if g[j] == 0 and st[j] == 0),
           "io_tables": table(r), "gold_tables": table(rg)}
    gw = [int(asof(gweekly, d)) for d in dates]
    rec["g_vs_weekly_csv_mismatches"] = int(sum(1 for i in range(len(g)) if g[i] != gw[i]))
    rec["decision_dates_first5"] = [str(x.date()) for x in dates[:5]]
    rec["decision_dates_last3"] = [str(x.date()) for x in dates[-3:]]
    rec["weeks_per_decision_gap_over_7_days"] = int(sum(1 for i in range(1, len(dates)) if (dates[i] - dates[i - 1]).days > 7))
    # the quarterly resets (first session of Jan/Apr/Jul/Oct, plan decision 2) that fall in the window while the rule is IN are an engine matter; count quarter starts only
    qs = [x for x in cal if x > cal[0] and (x.month in (1, 4, 7, 10)) and cal[cal < x][-1].month != x.month and (cal[cal < x][-1].month in (12, 3, 6, 9))]
    rec["quarter_start_sessions_in_window"] = len(qs)
    rec["_dates"] = dates; rec["_st"] = st; rec["_g"] = g
    return rec


def _spells_touching_out(g, st):
    j = 0
    while j < len(g):
        k = j
        while k + 1 < len(g) and g[k + 1] == g[j]:
            k += 1
        if any(st[i] == 0 for i in range(j, k + 1)):
            yield (j, k)
        j = k + 1


def main():
    for k, rel in FILES.items():
        ad.require(rel)
    ad.guard_window(FILES["SC100"], SC_FIRST_READ)
    cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(AA / FILES["cal"])["date"])))
    cal_all = cal_all[cal_all <= pd.Timestamp("2019-01-04")]
    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(AA / FILES[n], parse_dates=["Date"]).dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        if n == "SC100":
            d = d[d.index >= SC_FIRST_READ]                # rule 7: nothing before the window start is kept
        sig[n] = d
    gm = pd.read_excel(AA / FILES["gold"], parse_dates=["Date"])
    gsig = gm.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gweekly = pd.read_csv(AA / FILES["gold_weekly"], parse_dates=["review"]).dropna(subset=["signal"]).set_index("review")["signal"]
    out = {"window": [str(T0.date()), str(END.date())], "r3_start": str(R3_START.date()), "g_first_row": str(gsig.index.min().date()), "g_last_row": str(gsig.index.max().date()),
           "sc100_signal_rows_read_from": str(sig["SC100"].index.min().date()), "seeds": {k: v + ["draw_id"] for k, v in SEEDS.items()}}
    w_full = window(cal_all, sig, gsig, gweekly, T0)
    w_r3 = window(cal_all, sig, gsig, gweekly, cal_all[cal_all >= R3_START][0])
    out["full"] = {k: v for k, v in w_full.items() if not k.startswith("_")}
    out["r3"] = {k: v for k, v in w_r3.items() if not k.startswith("_")}
    # the weights: typed constants against the T07 counts file
    t07 = json.loads(T07_COUNTS.read_text(encoding="utf-8"))
    chk = {}
    for b, (L, M, S) in WEIGHTS.items():
        x = t07["books"][b]["full"]["mean_band_share_all_weeks"]
        tot = x["Large"] + x["Mid"] + x["Small and below"]
        chk[b] = {"sum_typed": round(L + M + S, 10), "max_abs_diff_vs_t07_renormalised": round(max(abs(L - x["Large"] / tot), abs(M - x["Mid"] / tot), abs(S - x["Small and below"] / tot)), 10)}
        assert abs(L + M + S - 1) < 1e-7 and chk[b]["max_abs_diff_vs_t07_renormalised"] < 1e-7, (b, chk[b])
    out["weights"] = {"typed": WEIGHTS, "check_vs_t07": chk, "t07_file": "tests/T07/logs/step_1_counts.json", "t07_file_sha256": hashlib.sha256(T07_COUNTS.read_bytes()).hexdigest()}
    bad = []
    for wname in ("full", "r3"):
        x = out[wname]
        for kind in ("io_tables", "gold_tables"):
            for state, v in x[kind].items():
                if not (v["feasible"] and v["rule_inside_bounds"]):
                    bad.append((wname, kind, state, v["k"], v["S"], v["lo"], v["hi"]))
    out["problems"] = bad
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs" / "step_1_spell_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for wname, x in (("full window", out["full"]), ("R3 window", out["r3"])):
        print(f"\n{wname}: {x['start']} -> {x['end']}, {x['sessions']} sessions, {x['weeks']} weekly decisions; decisions start {x['decision_dates_first5']} ... {x['decision_dates_last3']}; gaps > 7 days {x['weeks_per_decision_gap_over_7_days']}")
        print(f"  in/out: first {x['first_state']} last {x['last_state']}; in {x['in_spells']} spells (S {x['S_in']}) {x['in_lengths']}; out {x['out_spells']} spells (S {x['S_out']}) {x['out_lengths']}; round trips {x['round_trips']}")
        for lab, t in (("in/out", x["io_tables"]), ("gold", x["gold_tables"])):
            for st_, v in t.items():
                nm = ("BUY" if st_ == "in" else "SELL") if lab == "gold" else st_
                print(f"    {lab} {nm}: k {v['k']}, S {v['S']}, shortest {v['shortest']}, bounds [{v['lo']}, {v['hi']}], feasible {v['feasible']}, rule inside {v['rule_inside_bounds']}, n_ways {int(v['n_ways']):,}")
        print(f"  gold: first {x['g_first_state']} last {x['g_last_state']}; BUY {x['g_buy_spells']} spells (S {x['g_S_buy']}) {x['g_buy_lengths']}; SELL {x['g_sell_spells']} (S {x['g_S_sell']}) {x['g_sell_lengths']}; shortest {x['g_shortest']}")
        print(f"  gold flips {x['g_flips']}: {x['g_flips_while_out_both_sides']} while OUT both sides (sleeve trades) {x['g_flip_dates_while_out']}, {x['g_flips_on_an_exit_decision']} on an exit decision, {x['g_flips_while_in']} while IN; "
              f"spells touching OUT weeks {x['g_spells_with_an_out_week']}; OUT weeks g BUY/SELL {x['g_weeks_buy_while_out']}/{x['g_weeks_sell_while_out']}; g vs D24b weekly csv mismatches {x['g_vs_weekly_csv_mismatches']}; quarter-start sessions {x['quarter_start_sessions_in_window']}")
    print(f"\nSmallcap 100 signal rows read from {out['sc100_signal_rows_read_from']} (restriction 2011-11-25); weights check: {chk}")
    print("feasibility and rule-inside-bounds: all tables ok" if not bad else f"PROBLEM: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
