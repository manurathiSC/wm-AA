"""T16 Step 1: regime counts for W1 (T11's window, T15's inputs) and W2 (T08's window EXTENDED to 2026-11-20), plus the OUT-SELL basket B (the indices whose own
SIGN is BUY), k = |B|, the B stretches inside each OUT-SELL spell, and the trades each of the ten rules would make. Counts only: no price, NAV or return is read.

    python tests/T16/spell_counts.py        writes tests/T16/logs/step_1_spell_counts.json and prints a table

Fork of tests/T15/spell_counts.py. Reads only APPROVED rows of data/APPROVED_DATA.md (every file through approved_data.require). Inputs: W1 exactly T15's (D26 calendar,
D24b MAUc1, D03 extended_2026-10-30 Masters, D05 basket dates); W2 = D17 published-NAV dates of extended_2026-11-25 as the calendar (per book), cut at the last date every
signal role reaches (2026-11-20), D24c MAUc1, D03 extended_2026-11-20 Masters.
Decision rule as T06/T08/T11/T14/T15: T0, then the last session of every later ISO week to the window end; IN iff the latest Master row on or before the date is BUY in all
three indices; g = SIGN of the latest MAUc1 Master row on or before the date. Regimes: IN; OUT-BUY (not IN, g BUY); OUT-SELL (not IN, g SELL).
In OUT-SELL B = the indices whose own SIGN is BUY at the decision (0, 1 or 2 of Nifty100, MC100, SC100), k = |B|.
Trade trigger of the six T14 rules: a trade is due on the session after decision j (j >= 1, a session exists) iff e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1]).
Trade trigger of -idx: the target vector changes. Targets: IN -> parent; OUT-BUY -> the base sleeve; OUT-SELL -> cash + each index of B in equal parts.
So the target key is ("IN",), ("OB",) or ("OS", B); a change of the key is a trade (a change of B inside OUT-SELL included); a change of an index SIGN while IN or OUT-BUY is not.
NEW in T16, -all: OUT-SELL -> cash 0.25 + each of the three indices 0.25 whatever B; the key is ("IN",), ("OB",) or ("OS",), so only regime entries and exits trade.
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
INDICES = ("Nifty100", "MC100", "SC100")
W1_T0, W1_END, W1_R3 = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02"), pd.Timestamp("2015-01-02")
W2_LIVE = pd.Timestamp("2021-11-01")
W2_END = pd.Timestamp("2026-11-20")      # D4 (Manu 2026-11-26): the latest date every signal role reaches
FILES = {
    "cal_w1": DIR + "extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv",
    "Nifty100": DIR + "extended_2026-10-30/Master/Master_Nifty100.xlsx",
    "MC100": DIR + "extended_2026-10-30/Master/Master_MC100.xlsx",
    "SC100": DIR + "extended_2026-10-30/Master/Master_SC100.xlsx",
    "Nifty100_w2": DIR + "extended_2026-11-20/Master/Master_Nifty100.xlsx",
    "MC100_w2": DIR + "extended_2026-11-20/Master/Master_MC100.xlsx",
    "SC100_w2": DIR + "extended_2026-11-20/Master/Master_SC100.xlsx",
    "gold_w1": DIR + "extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx",
    "gold_w2": DIR + "extended_2026-11-20/MAUc1_from_2003/Master_MAUc1.xlsx",
}
for p in PARENTS:
    FILES["pub_" + p] = DIR + f"extended_2026-11-25/published_nav/{p}.csv"
    FILES["rebal_" + p] = DIR + f"frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv"

RULES = ["50-orig", "50-half", "50-liq", "50-idx", "50-all", "80-orig", "80-half", "80-liq", "80-idx", "80-all"]


def targets(rule, st, g, B):
    """Target for one decision. st = 1 IN, g = 1 gold BUY, B = tuple of BUY indices (used by -idx in OUT-SELL only).
    Returns ("t14", e, gw) for the six T14 rules and ("idx", key) for -idx."""
    base, kind = rule.split("-")
    if kind == "idx":
        return ("idx", ("IN",) if st == 1 else (("OB",) if g else ("OS",) + tuple(B)))
    if kind == "all":
        return ("idx", ("IN",) if st == 1 else (("OB",) if g else ("OS",)))
    gw_out = (0.5 if base == "50" else (0.8 if g else 0.2))
    if st == 1:
        return ("t14", 1.0, gw_out)
    if g == 0 and kind == "half":
        return ("t14", 0.5, 1.0)
    if g == 0 and kind == "liq":
        return ("t14", 0.0, 0.0)
    return ("t14", 0.0, gw_out)


def trade_due(a, b):
    if a[0] == "idx":
        return a[1] != b[1]
    return a[1] != b[1] or (a[1] < 1 and a[2] != b[2])


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
    st, g, B = [], [], []
    for i in idx:
        d = cal[i]
        buys = tuple(n for n in INDICES if asof(sig[n], d) == "BUY")
        st.append(int(len(buys) == 3))
        g.append(int(asof(gsig, d) == "BUY"))
        B.append(buys)
    return cal, idx, st, g, B


def bname(b):
    return "+".join(b) if b else "cash"


def summarise(cal, idx, st, g, B):
    reg = ["IN" if s else ("OUT-BUY" if gg else "OUT-SELL") for s, gg in zip(st, g)]
    rr = runs(reg)
    spells = {k: [c for v, c in rr if v == k] for k in ("IN", "OUT-BUY", "OUT-SELL")}
    srun = runs(st)
    ins, outs = [c for v, c in srun if v == 1], [c for v, c in srun if v == 0]
    sell_spells, bchanges = [], 0
    j = 0
    for v, c in rr:
        if v == "OUT-SELL":
            seq = runs([B[j + q] for q in range(c)])
            bchanges += len(seq) - 1
            sell_spells.append({"first_decision": str(cal[idx[j]].date()), "last_decision": str(cal[idx[j + c - 1]].date()), "weeks": c,
                                "entered_from": (reg[j - 1] if j > 0 else "start"), "exited_to": (reg[j + c] if j + c < len(reg) else "window end"),
                                "B_sequence": [[bname(b), n] for b, n in seq],
                                "weeks_holding_an_index": sum(n for b, n in seq if len(b) > 0)})
        j += c
    sell_k = [len(B[q]) for q in range(len(B)) if reg[q] == "OUT-SELL"]
    T = len(cal)
    trades = {}
    for r in RULES:
        tg = [targets(r, s, gg, b) for s, gg, b in zip(st, g, B)]
        due = [q for q in range(1, len(tg)) if idx[q] + 1 < T and trade_due(tg[q], tg[q - 1])]
        trades[r] = {"trades_from_regime_gold_and_B_changes": len(due)}
    idx_B_trades = sum(1 for q in range(1, len(B)) if idx[q] + 1 < T and reg[q] == "OUT-SELL" and reg[q - 1] == "OUT-SELL" and B[q] != B[q - 1])
    return {"start": str(cal[0].date()), "end": str(cal[-1].date()), "sessions": len(cal), "weeks": len(st), "first_state": st[0], "last_state": st[-1],
            "weeks_in": sum(ins), "weeks_out": sum(outs), "in_spells": len(ins), "out_spells": len(outs), "round_trips": min(len(ins), len(outs)),
            "weeks_IN": sum(spells["IN"]), "weeks_OUT_BUY": sum(spells["OUT-BUY"]), "weeks_OUT_SELL": sum(spells["OUT-SELL"]),
            "OUT_SELL_spells": len(spells["OUT-SELL"]), "OUT_SELL_lengths": spells["OUT-SELL"],
            "OUT_SELL_weeks_k0": sell_k.count(0), "OUT_SELL_weeks_k1": sell_k.count(1), "OUT_SELL_weeks_k2": sell_k.count(2),
            "OUT_SELL_weeks_holding_an_index": sum(1 for k in sell_k if k > 0),
            "OUT_SELL_spells_holding_an_index": sum(1 for s in sell_spells if s["weeks_holding_an_index"] > 0),
            "B_changes_inside_OUT_SELL": bchanges, "idx_trades_from_B_change_alone": idx_B_trades,
            "OUT_SELL_spell_table": sell_spells, "g_flips": sum(1 for q in range(1, len(g)) if g[q] != g[q - 1]), "g_first_state": g[0],
            "rules": trades,
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


def read_sig(files):
    sig = {}
    for n in INDICES:
        d = pd.read_excel(AA / files[n], parse_dates=["Date"]).dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        d = d[~d.index.duplicated(keep="last")]
        if n == "SC100":
            d = d[d.index >= SC_USABLE_FROM]
        sig[n] = d
    return sig


def main():
    for k, rel in FILES.items():
        ad.require(rel)
    ad.guard_window(FILES["SC100"], SC_USABLE_FROM)
    ad.guard_window(FILES["SC100_w2"], SC_USABLE_FROM)
    sig = read_sig(FILES)
    sig2 = read_sig({n: FILES[n + "_w2"] for n in INDICES})
    last2 = {n: str(s_.index.max().date()) for n, s_ in sig2.items()}
    assert len(set(last2.values())) == 1, last2
    SIG_END2 = max(s_.index.max() for s_ in sig2.values())

    def gold(key):
        gm = pd.read_excel(AA / FILES[key], parse_dates=["Date"])
        s = gm.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return s[~s.index.duplicated(keep="last")]
    g1, g2 = gold("gold_w1"), gold("gold_w2")
    GOLD_END2 = g2.index.max()
    # W2 ends at the earliest of the signal roles and the pinned end (D4); the engine asserts the same
    END2 = min(SIG_END2, GOLD_END2, W2_END)
    out = {"END_W2": str(END2.date()), "signal_ends_w2": {**last2, "MAUc1": str(GOLD_END2.date())},
           "W1": [str(W1_T0.date()), str(W1_END.date())], "seeds_note": "T16 draws nothing (no null, Manu's waiver)",
           "w1": {}, "w2": {}, "baskets_w1": {p: baskets_w1(p) for p in PARENTS},
           "new_w2_weeks": {str(d.date()): {**{n: sig2[n].loc[d] for n in INDICES}, "MAUc1": g2.loc[d]}
                            for d in pd.DatetimeIndex(["2026-11-06", "2026-11-13", "2026-11-20"]) if d in g2.index}}
    cal1_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(AA / FILES["cal_w1"])["date"])))
    for name, start in (("full", W1_T0), ("r3", W1_R3)):
        cal = cal1_all[(cal1_all >= start) & (cal1_all <= W1_END)]
        assert cal[0] == start or name == "r3"
        out["w1"][name] = summarise(*regimes(cal, sig, g1, W1_END))
    for p in PARENTS:
        cal_all = read_pub_dates(p)
        cal = cal_all[cal_all <= END2]
        out["w2"][p] = {"full": summarise(*regimes(cal, sig2, g2, END2))}
        live = cal[cal >= W2_LIVE]
        out["w2"][p]["live"] = summarise(*regimes(live, sig2, g2, END2))
    for w, x in [("W1 full", out["w1"]["full"]), ("W1 r3", out["w1"]["r3"])] + [(f"W2 {p}", out["w2"][p]["full"]) for p in PARENTS] + [(f"W2 live {p}", out["w2"][p]["live"]) for p in PARENTS]:
        for b in ("50", "80"):   # -all trades only on regime entries and exits, so it trades exactly as -liq does
            assert x["rules"][b + "-all"]["trades_from_regime_gold_and_B_changes"] == x["rules"][b + "-liq"]["trades_from_regime_gold_and_B_changes"], (w, b)
    out["problems"] = [(w, k) for w in ("full", "r3") for k, v in out["w1"].items() if k == w and not v["reportable"]]
    out["problems"] += [(p, "full") for p in PARENTS if not out["w2"][p]["full"]["reportable"]]
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs" / "step_1_spell_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    def show(label, x):
        print(f"{label}: {x['start']} -> {x['end']}, {x['sessions']} sessions, {x['weeks']} decisions; IN {x['weeks_IN']} OUT-BUY {x['weeks_OUT_BUY']} OUT-SELL {x['weeks_OUT_SELL']}; "
              f"OUT-SELL spells {x['OUT_SELL_spells']} {x['OUT_SELL_lengths']}; k0/k1/k2 weeks {x['OUT_SELL_weeks_k0']}/{x['OUT_SELL_weeks_k1']}/{x['OUT_SELL_weeks_k2']}; "
              f"index-holding weeks {x['OUT_SELL_weeks_holding_an_index']} in {x['OUT_SELL_spells_holding_an_index']} spells; B changes {x['B_changes_inside_OUT_SELL']} "
              f"({x['idx_trades_from_B_change_alone']} traded); reportable {x['reportable']}")
        print("   trades: " + ", ".join(f"{r} {v['trades_from_regime_gold_and_B_changes']}" for r, v in x["rules"].items()))
    show("W1 full", out["w1"]["full"]); show("W1 R3 ", out["w1"]["r3"])
    for p in PARENTS:
        show(f"W2 {p} full", out["w2"][p]["full"]); show(f"W2 {p} live", out["w2"][p]["live"])
    for lab, x in (("W1", out["w1"]["full"]), ("W2 SCMO_0003", out["w2"]["SCMO_0003"]["full"])):
        print(lab, "spells:")
        for s in x["OUT_SELL_spell_table"]:
            print("  ", s["first_decision"], s["weeks"], "wk", "from", s["entered_from"], "to", s["exited_to"], "|", ", ".join(f"{b} {n}" for b, n in s["B_sequence"]))
    print("problems:", out["problems"] or "none")
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
