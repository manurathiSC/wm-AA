"""T14 Step 1: regime counts for W1 (T11's window) and W2 (T08's window): IN / OUT-BUY / OUT-SELL weeks and spells, the trades each of the six rules would make,
and reportability. Counts only: no price, NAV or return is read.

    python tests/T14/spell_counts.py        writes tests/T14/logs/step_1_spell_counts.json and prints a table

Fork of tests/T11/spell_counts.py. Reads only APPROVED rows of data/APPROVED_DATA.md (every file through approved_data.require). Each window uses the inputs of the
test it extends (PLAN section 3): W1 = D26 calendar, D24b MAUc1, D05 basket dates; W2 = D17 EXTENDED published-NAV dates as the calendar (per book: SCMO_0007 starts 2019-01-04),
D24 MAUc1. Index signals: D03 extended Masters in both. Decision rule as T06/T08/T11: T0, then the last session of every later ISO week to the window end;
IN iff the latest Master row on or before the date is BUY in all three indices; g = SIGN of the latest MAUc1 Master row on or before the date.
Regimes: IN; OUT-BUY (not IN, g BUY); OUT-SELL (not IN, g SELL). Targets per rule (PLAN section 2) and the trade trigger of the engines:
a trade is due on the session after decision j (j >= 1, a session exists) iff e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1]).
"""
import json
import sys
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import approved_data as ad  # noqa: E402

DIR = "Historical Data/"
SC_USABLE_FROM = pd.Timestamp("2011-11-25")
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
W1_T0, W1_END, W1_R3 = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02"), pd.Timestamp("2015-01-02")
W2_LIVE = pd.Timestamp("2021-11-01")
FILES = {
    "cal_w1": DIR + "extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv",
    "Nifty100": DIR + "extended_2026-10-30/Master/Master_Nifty100.xlsx",
    "MC100": DIR + "extended_2026-10-30/Master/Master_MC100.xlsx",
    "SC100": DIR + "extended_2026-10-30/Master/Master_SC100.xlsx",
    "gold_w1": DIR + "extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx",
    "gold_w2": DIR + "extended_2026-11-06/MAUc1/Master_MAUc1.xlsx",
}
for p in PARENTS:
    FILES["pub_" + p] = DIR + f"extended_2026-11-06/published_nav/{p}.csv"
    FILES["rebal_" + p] = DIR + f"frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv"

RULES = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]


def targets(rule, st, g):
    """(e, gw) for one decision. st = 1 IN, g = 1 gold BUY. PLAN section 2 table. gw while IN is carried but never traded on."""
    base, kind = rule.split("-")
    gw_out = (0.5 if base == "50" else (0.8 if g else 0.2))
    if st == 1:
        return 1.0, gw_out
    if g == 0 and kind == "half":
        return 0.5, 1.0
    if g == 0 and kind == "liq":
        return 0.0, 0.0
    return 0.0, gw_out


def asof(series, d):
    i = series.index.searchsorted(d, side="right") - 1
    assert i >= 0, f"no row on or before {d.date()}"
    return series.iloc[i]


def runs(x):
    out, cur, c = [], x[0], 0
    for v in x:
        if v == cur:
            c += 1
        else:
            out.append((cur, c)); cur, c = v, 1
    out.append((cur, c))
    return out


def decision_dates(cal):
    iso = cal.isocalendar()
    wk = pd.Series(range(len(cal)), index=cal)
    last = sorted(wk.groupby([iso.year.values, iso.week.values]).max().values)
    return [0] + [int(i) for i in last if i > 0]


def regimes(cal, sig, gsig, end):
    cal = cal[cal <= end]
    idx = decision_dates(cal)
    st, g = [], []
    for i in idx:
        d = cal[i]
        st.append(int(all(asof(s, d) == "BUY" for s in sig.values())))
        g.append(int(asof(gsig, d) == "BUY"))
    return cal, idx, st, g


def summarise(cal, idx, st, g):
    reg = ["IN" if s else ("OUT-BUY" if gg else "OUT-SELL") for s, gg in zip(st, g)]
    rr = runs(reg)
    spells = {k: [c for v, c in rr if v == k] for k in ("IN", "OUT-BUY", "OUT-SELL")}
    srun = runs(st)
    ins, outs = [c for v, c in srun if v == 1], [c for v, c in srun if v == 0]
    sell_spells = []
    j = 0
    for v, c in rr:
        if v == "OUT-SELL":
            sell_spells.append({"first_decision": str(cal[idx[j]].date()), "last_decision": str(cal[idx[j + c - 1]].date()), "weeks": c,
                                "entered_from": (reg[j - 1] if j > 0 else "start"), "exited_to": (reg[j + c] if j + c < len(reg) else "window end")})
        j += c
    trades = {}
    T = len(cal)
    for r in RULES:
        tg = [targets(r, s, gg) for s, gg in zip(st, g)]
        due = [j for j in range(1, len(tg)) if idx[j] + 1 < T and (tg[j][0] != tg[j - 1][0] or (tg[j][0] < 1 and tg[j][1] != tg[j - 1][1]))]
        trades[r] = {"trades_from_regime_and_gold_changes": len(due), "weeks_with_e_0.5": sum(1 for e, _ in tg if e == 0.5),
                     "weeks_holding_no_parent_no_gold": sum(1 for e, gw in tg if e == 0 and gw == 0)}
    return {"start": str(cal[0].date()), "end": str(cal[-1].date()), "sessions": len(cal), "weeks": len(st), "first_state": st[0], "last_state": st[-1],
            "weeks_in": sum(ins), "weeks_out": sum(outs), "in_spells": len(ins), "out_spells": len(outs), "round_trips": min(len(ins), len(outs)),
            "in_lengths": ins, "out_lengths": outs,
            "weeks_IN": sum(spells["IN"]), "weeks_OUT_BUY": sum(spells["OUT-BUY"]), "weeks_OUT_SELL": sum(spells["OUT-SELL"]),
            "OUT_SELL_spells": len(spells["OUT-SELL"]), "OUT_SELL_lengths": spells["OUT-SELL"], "OUT_BUY_spells": len(spells["OUT-BUY"]), "OUT_BUY_lengths": spells["OUT-BUY"],
            "OUT_SELL_spell_table": sell_spells,
            "OUT_SELL_share_of_weeks": round(sum(spells["OUT-SELL"]) / len(st), 4), "g_flips": sum(1 for j in range(1, len(g)) if g[j] != g[j - 1]),
            "g_first_state": g[0], "rules": trades,
            "reportable": bool(min(len(ins), len(outs)) >= 4 and len(spells["OUT-SELL"]) >= 4)}


def read_pub_dates(p):
    n = pd.read_csv(AA / FILES["pub_" + p])
    assert (n["_id.scid"] == p).all()
    return pd.DatetimeIndex(sorted(pd.to_datetime(n["_id.date"], format="%Y/%m/%d")))


def baskets_w1(parent):
    h = pd.read_csv(AA / FILES["rebal_" + parent], usecols=["skipped", "date", "availableDate"]).drop_duplicates(["date"]).copy()
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    h = h.sort_values("eff")
    first = h[h["eff"] >= pd.Timestamp("2014-07-01")].iloc[0]["eff"]
    win = h[(h["eff"] >= first) & (h["eff"] <= W1_END)]
    return {"first_effective_on_or_after_2014-07-01": str(first.date()), "baskets_T0_to_END": len(win), "effective_dates": [str(x.date()) for x in win["eff"]]}


def main():
    for k, rel in FILES.items():
        ad.require(rel)
    ad.guard_window(FILES["SC100"], SC_USABLE_FROM)
    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(AA / FILES[n], parse_dates=["Date"]).dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        d = d[~d.index.duplicated(keep="last")]
        if n == "SC100":
            d = d[d.index >= SC_USABLE_FROM]
        sig[n] = d
    END2 = max(s.index.max() for s in sig.values())
    assert len({s.index.max() for s in sig.values()}) == 1
    def gold(key):
        gm = pd.read_excel(AA / FILES[key], parse_dates=["Date"])
        s = gm.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return s[~s.index.duplicated(keep="last")]
    g1, g2 = gold("gold_w1"), gold("gold_w2")
    out = {"END_W2": str(END2.date()), "W1": [str(W1_T0.date()), str(W1_END.date())], "seeds_note": "T14 reuses T11's seeds (W1) and T08's (W2); prefix 17 reserved, none drawn",
           "w1": {}, "w2": {}, "baskets_w1": {p: baskets_w1(p) for p in PARENTS}}
    cal1_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(AA / FILES["cal_w1"])["date"])))
    for name, start in (("full", W1_T0), ("r3", W1_R3)):
        cal = cal1_all[(cal1_all >= start) & (cal1_all <= W1_END)]
        assert cal[0] == start or name == "r3"
        out["w1"][name] = summarise(*regimes(cal, sig, g1, W1_END))
    for p in PARENTS:
        cal_all = read_pub_dates(p)
        cal = cal_all[cal_all <= END2]
        out["w2"][p] = {"full": summarise(*regimes(cal, sig, g2, END2))}
        live = cal[cal >= W2_LIVE]
        # the live window has its own spells (T08 R3): decisions from the first session on or after 2021-11-01
        out["w2"][p]["live"] = summarise(*regimes(live, sig, g2, END2))
    out["problems"] = [(w, k) for w in ("full", "r3") for k, v in out["w1"].items() if k == w and not v["reportable"]]
    out["problems"] += [(p, "full") for p in PARENTS if not out["w2"][p]["full"]["reportable"]]
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs" / "step_1_spell_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    def show(label, x):
        print(f"{label}: {x['start']} -> {x['end']}, {x['sessions']} sessions, {x['weeks']} decisions; IN {x['weeks_IN']} OUT-BUY {x['weeks_OUT_BUY']} OUT-SELL {x['weeks_OUT_SELL']} "
              f"({x['OUT_SELL_share_of_weeks']:.1%}); OUT-SELL spells {x['OUT_SELL_spells']} {x['OUT_SELL_lengths']}; in-or-out round trips {x['round_trips']} (IN spells {x['in_spells']}, OUT {x['out_spells']}); "
              f"first state {x['first_state']}; reportable {x['reportable']}")
        print("   trades from regime+gold changes: " + ", ".join(f"{r} {v['trades_from_regime_and_gold_changes']}" for r, v in x["rules"].items()))
    show("W1 full", out["w1"]["full"]); show("W1 R3 ", out["w1"]["r3"])
    for p in PARENTS:
        show(f"W2 {p} full", out["w2"][p]["full"]); show(f"W2 {p} live", out["w2"][p]["live"])
    print("problems:", out["problems"] or "none")
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
