"""T08 Step 1: spell counts of the three-index switch AND of the MAUc1 gold signal on the latest approved data. Counts only: no price, NAV or return is read.

    python tests/T08/spell_counts.py        writes tests/T08/logs/step_1_spell_counts.json and prints a table

Reads only APPROVED rows of data/APPROVED_DATA.md: the extended published NAVs (D17, calendar only), the extended index Masters (D03, which set the window
end 2026-10-30) and Master_MAUc1.xlsx (D24, the gold signal). Decision rule as T06: T0, then the last D17 session of every later ISO week up to the window
end; IN iff the latest Master row on or before the date is BUY in all three indices; g = SIGN of the latest MAUc1 Master row on or before the date.
Cross-checks: the in/out states equal T06's decisions.csv on every shared decision date; g equals the `signal` column of D24's weekly CSV.
Used to fix the pre-registration (section 2: what was already known; the bounds of N4.10 and of N4.10-g) before any engine code exists.
Deviation from the plan, disclosed: the plan said Step 1 would also list the bar ranges on the raw-fill GOLDBEES sessions; that reads prices, so only the
sessions are counted here and the ranges are left to robustness R7 (after the freeze).
"""
import json
import sys
from math import comb
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "data"))
import check_approved_data as CA  # noqa: E402

BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
LIVE_START = pd.Timestamp("2021-11-01")
MCX_LAST = pd.Timestamp("2026-09-28")        # D12's last date: GOLDBEES fills after it use the raw OHLC4
APPROVED = {r["file"] for r in CA.rows() if r["status"] == "APPROVED"}


def need(rel: str) -> Path:
    assert rel in APPROVED, f"not an APPROVED row of data/APPROVED_DATA.md: {rel}"
    return AA / rel


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
    return series.iloc[series.index.searchsorted(d, side="right") - 1]


def table(name, runs, bounds):
    """Per state: k, S, shortest, longest, bounds and the feasibility 2k<=S<=hi*k (with the state's own lo)."""
    out = {}
    for state, label in ((1, "in"), (0, "out")):
        ls = [c for v, c in runs if v == state]
        lo, hi = bounds[label]
        ok = len(ls) > 0 and lo * len(ls) <= sum(ls) <= hi * len(ls)
        out[label] = {"k": len(ls), "S": sum(ls), "lengths": ls, "shortest": min(ls) if ls else None,
                      "longest": max(ls) if ls else None, "lo": lo, "hi": hi, "feasible": bool(ok),
                      "n_ways": str(n_ways(len(ls), sum(ls), lo, hi)) if ok else "0"}
    return out


def main():
    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(need(f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx"), parse_dates=["Date"])
        sig[n] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    end = min(s.index.max() for s in sig.values())
    gm = pd.read_excel(need("Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx"), parse_dates=["Date"])
    gsig = gm.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gweekly = pd.read_csv(need("Historical Data/extended_2026-11-06/MAUc1/mauc1_supertrend_weekly_extended.csv"), parse_dates=["review"]).dropna(subset=["signal"]).set_index("review")["signal"]
    t06 = pd.read_csv(AA / "tests" / "T06" / "evidence" / "headline" / "decisions.csv")
    out = {"window_end": str(end.date()), "g_first_row": str(gsig.index.min().date()), "g_last_row": str(gsig.index.max().date()), "books": {}}
    raw_fill_sessions = {}
    per_book = {}
    for b in BOOKS:
        raw = pd.read_csv(need(f"Historical Data/extended_2026-11-06/published_nav/{b}.csv"))
        cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")))
        full_cal = cal_all[cal_all <= end]
        assert full_cal[-1] == end, f"{b}: the window end {end.date()} is not a D17 session"
        res = {"calendar_first": str(full_cal[0].date()), "calendar_last": str(full_cal[-1].date()),
               "d17_last": str(cal_all[-1].date())}
        for win, start in (("full", None), ("live", LIVE_START)):
            cal = full_cal if start is None else full_cal[full_cal >= start]
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
            # sleeve events: a g flip while the rule is OUT before and after (a sleeve rebalance trade). Flips with an exit on the same decision
            # are not extra trades (the exit uses the new g); flips while IN are not trades either.
            flips = [j for j in range(1, len(g)) if g[j] != g[j - 1]]
            flips_out = [j for j in flips if st[j] == 0 and st[j - 1] == 0]
            flips_exit = [j for j in flips if st[j] == 0 and st[j - 1] == 1]
            flips_in = [j for j in flips if st[j] == 1]
            sess_after_mcx = [str(x.date()) for x in cal if x > MCX_LAST]
            rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "weeks": len(st), "first_state": st[0], "last_state": st[-1],
                   "in_spells": len(ins), "out_spells": len(outs), "S_in": sum(ins), "S_out": sum(outs),
                   "in_lengths": ins, "out_lengths": outs, "longest_in": max(ins), "longest_out": max(outs),
                   "round_trips": min(len(ins), len(outs)),
                   "g_first_state": g[0], "g_last_state": g[-1], "g_buy_spells": len(buys), "g_sell_spells": len(sells),
                   "g_S_buy": sum(buys), "g_S_sell": sum(sells), "g_buy_lengths": buys, "g_sell_lengths": sells,
                   "g_shortest": min(buys + sells), "g_flips": len(flips), "g_flips_while_out_both_sides": len(flips_out),
                   "g_flips_on_an_exit_decision": len(flips_exit), "g_flips_while_in": len(flips_in),
                   "g_flip_dates_while_out": [str(dates[j].date()) for j in flips_out],
                   "g_spells_with_an_out_week": sum(1 for _ in _spells_touching_out(g, st)),
                   "g_weeks_buy_while_out": sum(1 for j in range(len(g)) if g[j] == 1 and st[j] == 0),
                   "g_weeks_sell_while_out": sum(1 for j in range(len(g)) if g[j] == 0 and st[j] == 0),
                   "sessions_after_mcx_range_end": len(sess_after_mcx), "sessions_after_mcx_range_end_first": sess_after_mcx[:1],
                   "sessions_after_mcx_range_end_last": sess_after_mcx[-1:]}
            if win == "full":
                e = t06[t06.book == b].reset_index(drop=True)
                shared = min(len(e), len(st))
                rec["t06_shared_decisions"] = shared
                rec["t06_state_mismatches"] = int(sum(int(e.state.iloc[i]) != st[i] for i in range(shared)))
                rec["t06_date_mismatches"] = int(sum(str(e.decision_date.iloc[i])[:10] != str(dates[i].date()) for i in range(shared)))
                # g against D24's weekly csv: a decision date maps to the latest weekly review on or before it
                gw = [int(asof(gweekly, d)) for d in dates]
                rec["g_vs_d24_weekly_csv_mismatches"] = int(sum(1 for i in range(len(g)) if g[i] != gw[i]))
            rec["_dates"] = dates; rec["_st"] = st; rec["_g"] = g
            res[win] = rec
        per_book[b] = res
    # bounds. in/out: lo 2 and the rule's longest spells over the full window (T06's convention). gold: lo = min(2, shortest actual spell of that state), hi = longest
    hi_in = max(per_book[b]["full"]["longest_in"] for b in BOOKS)
    hi_out = max(per_book[b]["full"]["longest_out"] for b in BOOKS)
    gb_buy = max(max(per_book[b]["full"]["g_buy_lengths"]) for b in BOOKS)
    gb_sell = max(max(per_book[b]["full"]["g_sell_lengths"]) for b in BOOKS)
    glo_buy = min(2, min(min(per_book[b]["full"]["g_buy_lengths"]) for b in BOOKS))
    glo_sell = min(2, min(min(per_book[b]["full"]["g_sell_lengths"]) for b in BOOKS))
    out["bounds"] = {"io": {"lo": 2, "hi_in": hi_in, "hi_out": hi_out},
                     "gold": {"lo_buy": glo_buy, "hi_buy": gb_buy, "lo_sell": glo_sell, "hi_sell": gb_sell}}
    feas = []
    for b in BOOKS:
        for win in ("full", "live"):
            x = per_book[b][win]
            io = table("io", spells(x["_st"]), {"in": (2, hi_in), "out": (2, hi_out)})
            gg = table("g", spells(x["_g"]), {"in": (glo_buy, gb_buy), "out": (glo_sell, gb_sell)})
            # the live window's first spells are partial; its own bounds are the same constants (T06 convention) and must still contain the actual spells
            for kind, tab in (("io", io), ("gold", gg)):
                for state, v in tab.items():
                    inside = all(v["lo"] <= L <= v["hi"] for L in v["lengths"])
                    feas.append({"book": b, "window": win, "series": kind, "state": ("buy" if (kind == "gold" and state == "in") else "sell" if kind == "gold" else state),
                                 "k": v["k"], "S": v["S"], "lo": v["lo"], "hi": v["hi"], "rule_inside_bounds": bool(inside),
                                 "feasible": v["feasible"], "n_ways": v["n_ways"]})
    out["feasibility"] = feas
    for b in BOOKS:
        out["books"][b] = {w: {k: v for k, v in per_book[b][w].items() if not k.startswith("_")} for w in ("full", "live")}
        out["books"][b].update({k: v for k, v in per_book[b].items() if k not in ("full", "live")})
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs" / "step_1_spell_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"window end {end.date()} (the last D03 row); D17 runs to {per_book[BOOKS[0]]['d17_last']}; MAUc1 Master {out['g_first_row']} -> {out['g_last_row']}")
    print(f"in/out bounds: lo 2, hi_in {hi_in}, hi_out {hi_out} | gold bounds: BUY [{glo_buy}, {gb_buy}], SELL [{glo_sell}, {gb_sell}]")
    for b in BOOKS:
        for win in ("full", "live"):
            x = out["books"][b][win]
            extra = (f" | vs T06 on {x['t06_shared_decisions']} shared decisions: {x['t06_state_mismatches']} state, {x['t06_date_mismatches']} date mismatches; g vs D24 weekly csv: {x['g_vs_d24_weekly_csv_mismatches']} mismatches") if win == "full" else ""
            print(f"{b} {win}: {x['start']} -> {x['end']}, {x['weeks']} weeks | in/out first {x['first_state']} last {x['last_state']}, in {x['in_spells']} (S {x['S_in']}, longest {x['longest_in']}), out {x['out_spells']} (S {x['S_out']}, longest {x['longest_out']}), round trips {x['round_trips']}")
            print(f"    gold first {x['g_first_state']} last {x['g_last_state']}: BUY {x['g_buy_spells']} spells (S {x['g_S_buy']}), SELL {x['g_sell_spells']} (S {x['g_S_sell']}), shortest {x['g_shortest']}; flips {x['g_flips']}: "
                  f"{x['g_flips_while_out_both_sides']} while OUT both sides (sleeve trades), {x['g_flips_on_an_exit_decision']} on an exit decision, {x['g_flips_while_in']} while IN; "
                  f"spells touching OUT weeks {x['g_spells_with_an_out_week']}; OUT weeks with g BUY/SELL {x['g_weeks_buy_while_out']}/{x['g_weeks_sell_while_out']}{extra}")
    x = out["books"][BOOKS[0]]["full"]
    print(f"sessions after the MCX range end ({MCX_LAST.date()}) up to the window end: {x['sessions_after_mcx_range_end']} ({x['sessions_after_mcx_range_end_first']} -> {x['sessions_after_mcx_range_end_last']}); flip dates while OUT: {x['g_flip_dates_while_out']}")
    bad = [f for f in feas if not (f["feasible"] and f["rule_inside_bounds"])]
    print("feasibility and rule-inside-bounds: all tables ok" if not bad else f"PROBLEM: {bad}")
    return 1 if bad else 0


def _spells_touching_out(g, st):
    """Yield each maximal run of g that contains at least one OUT week."""
    j = 0
    while j < len(g):
        k = j
        while k + 1 < len(g) and g[k + 1] == g[j]:
            k += 1
        if any(st[i] == 0 for i in range(j, k + 1)):
            yield (j, k)
        j = k + 1


if __name__ == "__main__":
    sys.exit(main())
