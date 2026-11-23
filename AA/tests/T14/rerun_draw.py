"""Reproduce one null draw of T14 from its id and compare it with the evidence.

    python tests/T14/rerun_draw.py --win w1 --book SCMO_0003 --family F1 --id 17 [--cost 20.8] [--span full|r3] [--cash lbes|liq] [--rule 50-half]
    python tests/T14/rerun_draw.py --win w2 --book SCMO_0003 --family F3 --id 5
    python tests/T14/rerun_draw.py --win w2 --book SCMO_0003 --family F5 --id 5 --gold-id 5     (both timings random; --gold-id only if it differs from --id)
    options: --run headline | --evidence DIR (the folder that holds w1/ and w2/)

Families (T14.md section 3, step 9): F1 = in-or-out N4.10 with the real gold signal (seed W1 [14, 6, id], W2 [6, id]); F2 = in-or-out N4.9 ([14, 3, id] / [3, id]); F3 = real in-or-out switch with
gold N4.10-g ([14, 11, 6, id] / [11, 6, id]); F4 = gold N4.9-g ([14, 11, 3, id] / [11, 3, id]); F5 = F1's in-or-out draw (id) with F3's gold draw (gold-id).
All six rules (50-orig, 50-half, 50-liq, 80-orig, 80-half, 80-liq) are run on the draw, as the engine does; --rule restricts the printout to one.

Uses the engine (analysis/t14_engine.py): Book, simulate, stats, spell_shuffle, free_length_draw, series_bounds, rule_arrays, regime_codes, trades_due, sessions_invested. The engine is imported on purpose
(as the T06, T08 and T11 rerun scripts do): this shows that a stored draw is reproducible from its id with the engine's own functions. The CAGR and the maximum drawdown are also recomputed here from the
rebuilt daily NAV with the formulas of T14.md section 3 step 8 (not the engine's `stats`) and compared with draws.csv.

For every rule it compares
  * every statistic with the row of <evidence>/<w>/draws.csv (end NAV, CAGR, drawdown, volatility, Ulcer index, days below -10%, longest time under water, Calmar, sessions, invested weeks, OUT-SELL weeks,
    sessions invested, trades due) to a relative 1e-12 (counts exactly);
  * the rebuilt weekly states with the rows of draw_states.npz (keys "<book>|<full or r3>|io|N4.9", "...|io|N4.10", "...|gold|N4.9-g", "...|gold|N4.10-g"; the LIQUIDCASE cell reuses the full-window states);
  * for the headline cell (full window, LBES, 20.8 bps; F1 and F3, the stored ids) the daily curve with draw_curves_20.8.npz (key "<book>|<family>|<rule>|<id>", float64; relative 1e-12).

Exit code 0 only if everything that exists in the evidence is equal. No stored row for the arguments is an error (exit 2).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(AA / "analysis"))
import t14_engine as E  # noqa: E402

SEEDS = {"F1": ("io", "N4.10"), "F2": ("io", "N4.9"), "F3": ("gold", "N4.10-g"), "F4": ("gold", "N4.9-g"), "F5": ("both", None)}


def lens(a, v):
    out, cur, c = [], int(a[0]), 0
    for x in a:
        if int(x) == cur:
            c += 1
        else:
            out.append((cur, c))
            cur, c = int(x), 1
    out.append((cur, c))
    return [n for s, n in out if s == v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", choices=["w1", "w2"], required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--family", choices=list(SEEDS), required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--gold-id", type=int, default=None, help="F5 only, if the gold draw id differs from --id")
    ap.add_argument("--cost", type=float, default=20.8)
    ap.add_argument("--span", choices=["full", "r3"], default="full")
    ap.add_argument("--cash", choices=["lbes", "liq"], default="lbes")
    ap.add_argument("--rule", choices=E.RULES, default=None)
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args()
    ev = (Path(a.evidence) if a.evidence else HERE / "evidence" / a.run) / a.win
    gid = a.id if a.gold_id is None else a.gold_id
    fam = a.family
    W = E.WINDOWS[a.win]
    sd = W["seeds"]

    bk = E.Book(a.book, a.win, start=(W["r3_start"] if a.span == "r3" else None), cash=a.cash)
    dec = bk.decisions()
    idx = dec["decision_idx"].values
    s_real = dec["state"].values.astype(int)
    g_real = dec["g"].values.astype(int)
    if a.span == "r3" and W["r3_bounds"] == "full":     # W2's live window uses the book's full-window bounds (T08)
        full = E.Book(a.book, a.win).decisions()
        bio, bgo = E.series_bounds(full["state"].values.astype(int)), E.series_bounds(full["g"].values.astype(int))
    else:
        bio, bgo = E.series_bounds(s_real), E.series_bounds(g_real)
    if fam in ("F1", "F5"):
        s = np.asarray(E.free_length_draw(s_real, a.id, bio, sd["io410"])).astype(int)
    elif fam == "F2":
        s = np.asarray(E.spell_shuffle(s_real, a.id, sd["io49"])).astype(int)
    else:
        s = s_real
    if fam in ("F3", "F5"):
        g = np.asarray(E.free_length_draw(g_real, gid, bgo, sd["g410"])).astype(int)
    elif fam == "F4":
        g = np.asarray(E.spell_shuffle(g_real, a.id, sd["g49"])).astype(int)
    else:
        g = g_real
    reg = E.regime_codes(s, g)
    print(f"{a.win} {a.book} {fam} id {a.id}{'' if gid == a.id else f' (gold id {gid})'}: span {a.span}, cash {a.cash}, {a.cost} bps; bounds in-or-out in {bio[1]} out {bio[0]}, gold BUY {bgo[1]} SELL {bgo[0]}; weeks {len(s)}; "
          f"IN weeks {int(s.sum())}; BUY weeks {int(g.sum())}; OUT-SELL weeks {int((reg == 2).sum())}; in-lengths {lens(s, 1)}; out-lengths {lens(s, 0)}; BUY-lengths {lens(g, 1)}; SELL-lengths {lens(g, 0)}")

    d = pd.read_csv(ev / "draws.csv")
    sub = d[(d.book == a.book) & (d.window == a.span) & (d.cash == a.cash) & (d.cost_bps == a.cost) & (d.family == fam) & (d.draw_id == a.id)]
    if fam == "F5" and gid != a.id:
        sub = sub.iloc[0:0]
        print("F5 rows of draws.csv pair the in-or-out draw and the gold draw of the SAME id; with --gold-id different from --id there is no stored row (only the states are compared)")
    ok, found = True, False
    close = lambda x, y: abs(float(x) - float(y)) <= 1e-12 * max(1.0, abs(float(y)))
    cz = ev / "draw_curves_20.8.npz"
    curves = np.load(cz) if cz.exists() else None
    for rule in ([a.rule] if a.rule else E.RULES):
        e_, gw_ = E.rule_arrays(rule, s, g)
        nav = E.simulate(bk, idx, e_, a.cost, gw=gw_, reg=E.reg_arg(rule, reg))
        stt = E.stats(nav)
        yrs = (len(nav) - 1) / 252
        cagr_h = nav[-1] ** (1 / yrs) - 1
        mdd_h = float((nav / np.maximum.accumulate(nav) - 1).min())
        td = len(E.trades_due(idx, bk.T, e_, gw_))
        si = int(E.sessions_invested(bk, idx, s))
        print(f"  {rule:8s} end NAV {stt['end_nav']:.10f}  CAGR {100 * stt['cagr']:.6f}%  max drawdown {100 * stt['max_dd']:.6f}%  (by hand from the NAV: CAGR {100 * cagr_h:.6f}%, drawdown {100 * mdd_h:.6f}%)  "
              f"trades due {td}  sessions invested {si}")
        ok &= close(stt["cagr"], cagr_h) and close(stt["max_dd"], mdd_h)
        row = sub[sub.rule == rule]
        if len(row):
            found = True
            r = row.iloc[0]
            diffs = {}
            for k in ("end_nav", "cagr", "max_dd", "vol", "ulcer", "calmar"):
                diffs[k] = abs(float(stt[k]) - float(r[k])) / max(1.0, abs(float(r[k])))
                ok &= close(stt[k], r[k])
            for k, v in (("days_below_10pct", int(stt["days_below_10pct"])), ("longest_underwater", int(stt["longest_underwater"])), ("sessions", int(stt["sessions"])),
                         ("invested_weeks", int(s.sum())), ("out_sell_weeks", int((reg == 2).sum())), ("sessions_invested", si), ("trades_due", td)):
                diffs[k] = abs(v - int(r[k]))
                ok &= v == int(r[k])
            print("           stored draws.csv row found; differences (relative for the floats, absolute for the counts):", {k: (f"{v:.1e}" if isinstance(v, float) else v) for k, v in diffs.items()})
        if curves is not None and a.span == "full" and a.cash == "lbes" and a.cost == 20.8 and fam in ("F1", "F3"):
            key = f"{a.book}|{fam}|{rule}|{a.id}"
            if key in curves.files:
                found = True
                c = curves[key].astype(float)
                rel = float(np.abs(np.asarray(nav, dtype=float) / c - 1).max()) if len(c) == len(nav) else float("inf")
                print(f"           draw_curves_20.8.npz[{key!r}]: maximum relative difference of the daily curve {rel:.1e} (need < 1e-12)")
                ok &= rel < 1e-12
    if not len(sub):
        print("  no stored draws.csv row for these arguments")
    zp = ev / "draw_states.npz"
    if zp.exists():
        z = np.load(zp)
        sw = "full" if a.cash == "liq" else a.span
        for kind, typ, arr, rid in (("io", {"F1": "N4.10", "F2": "N4.9", "F5": "N4.10"}.get(fam), s, a.id), ("gold", {"F3": "N4.10-g", "F4": "N4.9-g", "F5": "N4.10-g"}.get(fam), g, gid)):
            if typ is None:
                continue
            key = f"{a.book}|{sw}|{kind}|{typ}"
            if key in z.files and rid < z[key].shape[0]:
                found = True
                eq = bool(len(z[key][rid]) == len(arr) and (z[key][rid].astype(int) == arr).all())
                print(f"  draw_states.npz[{key!r}][{rid}] equal to the rebuilt states: {eq}")
                ok &= eq
            else:
                print(f"  draw_states.npz has no row for {key} id {rid}")
    if not found:
        print("nothing in the evidence to compare with")
        sys.exit(2)
    print("EQUAL" if ok else "DIFFERENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
