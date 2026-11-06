"""T06 Step 1: spell counts of the three-index switch on the latest approved data. Counts only: no price, NAV or return is read.

    python tests/T06/spell_counts.py        writes tests/T06/logs/step_1_spell_counts.json and prints a table

Reads only APPROVED rows of data/APPROVED_DATA.md: the published NAVs (D17, for the calendar) and the extended Master signal files (D03).
Decision rule as T03 section 3, steps 1-3: T0, then the last D17 session of every later ISO week; IN iff the latest Master row on or before the
date is BUY in all three indices. Cross-check: the states equal T03's decisions.csv on every shared decision date.
Used to fix the pre-registration (section 2: what was already known; the bounds of N4.10) before any engine code exists.
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


def main():
    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(need(f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx"), parse_dates=["Date"])
        sig[n] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    t03 = pd.read_csv(AA / "tests" / "T03" / "evidence" / "headline" / "decisions.csv")
    out = {"books": {}}
    for b in BOOKS:
        raw = pd.read_csv(need(f"Historical Data/parent_nav_2026-10-22/{b}.csv"))
        full_cal = pd.DatetimeIndex(sorted(pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")))
        res = {"calendar_first": str(full_cal[0].date()), "calendar_last": str(full_cal[-1].date())}
        for win, start in (("full", None), ("live", LIVE_START)):
            cal = full_cal if start is None else full_cal[full_cal >= start]
            wk = pd.Series(cal, index=cal)
            iso = cal.isocalendar()
            last = sorted(wk.groupby([iso.year.values, iso.week.values]).max().values)
            dates = [cal[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > cal[0]]
            st = []
            for d in dates:
                ok = 1
                for s in sig.values():
                    ok &= int(s.iloc[s.index.searchsorted(d, side="right") - 1] == "BUY")
                st.append(ok)
            r = spells(st)
            ins = [c for v, c in r if v == 1]
            outs = [c for v, c in r if v == 0]
            rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "weeks": len(st), "first_state": st[0], "last_state": st[-1],
                   "in_spells": len(ins), "out_spells": len(outs), "S_in": sum(ins), "S_out": sum(outs),
                   "in_lengths": ins, "out_lengths": outs, "longest_in": max(ins), "longest_out": max(outs),
                   "round_trips": min(len(ins), len(outs))}
            if win == "full":
                e = t03[t03.book == b].reset_index(drop=True)
                shared = min(len(e), len(st))
                rec["t03_shared_decisions"] = shared
                rec["t03_state_mismatches"] = int(sum(int(e.state.iloc[i]) != st[i] for i in range(shared)))
                rec["t03_date_mismatches"] = int(sum(str(e.decision_date.iloc[i])[:10] != str(dates[i].date()) for i in range(shared)))
            res[win] = rec
        out["books"][b] = res
    # bounds: the rule's longest spells over the full window, taken from the first book that has the maximum (all books share the series)
    hi_in = max(out["books"][b]["full"]["longest_in"] for b in BOOKS)
    hi_out = max(out["books"][b]["full"]["longest_out"] for b in BOOKS)
    out["bounds"] = {"lo": 2, "hi_in": hi_in, "hi_out": hi_out}
    feas = []
    for b in BOOKS:
        for win in ("full", "live"):
            x = out["books"][b][win]
            for state, k, S, hi in (("in", x["in_spells"], x["S_in"], hi_in), ("out", x["out_spells"], x["S_out"], hi_out)):
                ok = 2 * k <= S <= hi * k
                feas.append({"book": b, "window": win, "state": state, "k": k, "S": S, "lo": 2, "hi": hi, "feasible": bool(ok),
                             "n_ways": str(n_ways(k, S, 2, hi)) if ok else "0"})
    out["feasibility"] = feas
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs" / "step_1_spell_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"bounds: lo 2, hi_in {hi_in}, hi_out {hi_out}")
    for b in BOOKS:
        for win in ("full", "live"):
            x = out["books"][b][win]
            extra = f" | vs T03 on {x['t03_shared_decisions']} shared decisions: {x['t03_state_mismatches']} state and {x['t03_date_mismatches']} date mismatches" if win == "full" else ""
            print(f"{b} {win}: {x['start']} -> {x['end']}, {x['weeks']} weeks, first state {x['first_state']}, last {x['last_state']}, "
                  f"in {x['in_spells']} (S {x['S_in']}, longest {x['longest_in']}), out {x['out_spells']} (S {x['S_out']}, longest {x['longest_out']}), "
                  f"round trips {x['round_trips']}{extra}")
    bad = [f for f in feas if not f["feasible"]]
    print("feasibility: all windows and states feasible" if not bad else f"INFEASIBLE: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
