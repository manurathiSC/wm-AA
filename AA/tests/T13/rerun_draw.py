"""Reproduce one null draw from its id and compare it with the evidence.

    python tests/T13/rerun_draw.py --book SCMO_0003 --family F1 --id 11 --cost 20.8 [--window full|r3] [--cash lbes|liq] [--sleeve-mode timed|fixed50]
    python tests/T13/rerun_draw.py --book SCMO_0003 --family F3 --id 7  --cost 20.8
    python tests/T13/rerun_draw.py --book SCMO_0003 --family F5 --id 7 --gold-id 7 --cost 20.8        (both timings random; --gold-id only if it differs from --id)
    options: --run headline | --evidence DIR   (the evidence directory to compare with)

Families (T13.md section 2): F1 = in-or-out N4.10 (seed default_rng([16, 6, id])) with the real gold signal; F2 = in-or-out N4.9 ([16, 3, id]) with the real gold signal;
F3 = real in-or-out switch with gold N4.10-g ([16, 11, 6, id]); F4 = real switch with gold N4.9-g ([16, 11, 3, id]); F5 = F1's in-or-out draw (id) with F3's gold draw (gold-id).
The real in-or-out series is the 2-of-3 rule's (T13.md section 3 step 3: IN iff at least two of the three index SIGNs are BUY; the `state` column of the engine's
Book.decisions(), whose default is the 2-of-3 entry); T11's all-3 rule is a comparator only and has no draws. Seeds start with 16 (T11: 14).
--sleeve-mode fixed50 runs the draw with the sleeve fixed at 50/50 (the nulls of A1 and A2; the gold state does not enter).

Uses the engine (analysis/t13_engine.py): Book, simulate, stats, spell_shuffle, free_length_draw, series_bounds, sessions_invested, n_sleeve_trades. The engine is imported on purpose
(as T06's and T08's rerun scripts do): this script shows that a stored draw is reproducible from its id with the engine's own functions.

It runs the draw through the same simulator and compares
  * every statistic with the row of evidence/<run>/draws.csv (end NAV, CAGR, drawdown, volatility, Ulcer index, days below -10%, longest time under water, Calmar, sessions,
    invested weeks, spell counts, BUY weeks, gold spell counts, the in/out and BUY/SELL length strings, sessions invested, sleeve trades) to a relative 1e-12;
  * the rebuilt weekly states with the rows of draw_states.npz (keys "<book>|<window>|io|N4.9", "...|io|N4.10", "...|gold|N4.9-g", "...|gold|N4.10-g"; LIQ reuses the full-window states);
  * for the headline cell (full window, LBES, 20.8 bps, timed) the daily curve of F1 and F3 with draw_curves_20.8.npz (float32, relative 1e-6).

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
import t13_engine as E  # noqa: E402

SEEDS = {"F1": ("io", "N4.10"), "F2": ("io", "N4.9"), "F3": ("gold", "N4.10-g"), "F4": ("gold", "N4.9-g"), "F5": ("both", None)}


def spells(a):
    out, cur, c = [], int(a[0]), 0
    for x in a:
        if int(x) == cur:
            c += 1
        else:
            out.append((cur, c))
            cur, c = int(x), 1
    out.append((cur, c))
    return out


def lens(a, v):
    return [n for s, n in spells(a) if s == v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--family", choices=list(SEEDS), required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--gold-id", type=int, default=None, help="F5 only, if the gold draw id differs from --id")
    ap.add_argument("--cost", type=float, default=20.8)
    ap.add_argument("--window", choices=["full", "r3"], default="full")
    ap.add_argument("--cash", choices=["lbes", "liq"], default="lbes")
    ap.add_argument("--sleeve-mode", choices=["timed", "fixed50"], default="timed")
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    gid = a.id if a.gold_id is None else a.gold_id
    fam = a.family

    bk = E.Book(a.book, start=(E.R3_START if a.window == "r3" else None), cash=a.cash)
    dec = bk.decisions()
    idx = dec["decision_idx"].values
    s_real = dec["state"].values.astype(int)          # the 2-of-3 rule (T13); dec["state_all3"] is T11's rule, not drawn
    assert (s_real == (dec["n_buy"].values >= 2).astype(int)).all(), "the engine's state is not the 2-of-3 rule"
    g_real = dec["g"].values.astype(int)
    bio, bgo = E.series_bounds(s_real), E.series_bounds(g_real)
    if fam in ("F1", "F5"):
        s = np.asarray(E.free_length_draw(s_real, a.id, bio, E.SEED_IO_410)).astype(int)
    elif fam == "F2":
        s = np.asarray(E.spell_shuffle(s_real, a.id, E.SEED_IO_49)).astype(int)
    else:
        s = s_real
    if fam in ("F3", "F5"):
        g = np.asarray(E.free_length_draw(g_real, gid, bgo, E.SEED_G_410)).astype(int)
    elif fam == "F4":
        g = np.asarray(E.spell_shuffle(g_real, a.id, E.SEED_G_49)).astype(int)
    else:
        g = g_real
    if a.sleeve_mode == "fixed50":
        nav = E.simulate(bk, idx, s.astype(float), a.cost, gw=None)
        g_used = g_real
    else:
        nav = E.simulate(bk, idx, s.astype(float), a.cost, gw=np.where(g == 1, E.GW_BUY, E.GW_SELL))
        g_used = g
    stt = E.stats(nav)
    print("rebuilt:", {k: (round(v, 10) if isinstance(v, float) else v) for k, v in stt.items()})
    print(f"bounds in-or-out in {bio[1]} out {bio[0]}, gold BUY {bgo[1]} SELL {bgo[0]}; weeks {len(s)}; invested {int(s.sum())}; BUY weeks {int(g.sum())}; in-lengths {lens(s, 1)}; out-lengths {lens(s, 0)}; "
          f"BUY-lengths {lens(g, 1)}; SELL-lengths {lens(g, 0)}")

    ok, found = True, False
    d = pd.read_csv(ev / "draws.csv")
    row = d[(d.book == a.book) & (d.window == a.window) & (d.cash == a.cash) & (d.cost_bps == a.cost) & (d.family == fam) & (d.sleeve_mode == a.sleeve_mode) & (d.draw_id == a.id)]
    if len(row):
        found = True
        r = row.iloc[0]
        close = lambda x, y: abs(float(x) - float(y)) <= 1e-12 * max(1.0, abs(float(y)))
        diffs = {}
        for k in ("end_nav", "cagr", "max_dd", "vol", "ulcer", "calmar"):
            diffs[k] = abs(float(stt[k]) - float(r[k])) / max(1.0, abs(float(r[k])))
            ok &= close(stt[k], r[k])
        for k in ("days_below_10pct", "longest_underwater", "sessions"):
            diffs[k] = abs(int(stt[k]) - int(r[k]))
            ok &= int(stt[k]) == int(r[k])
        si = int(E.sessions_invested(bk, idx, s))
        ns = 0 if a.sleeve_mode == "fixed50" else int(E.n_sleeve_trades(idx, bk.T, s, g_used))
        for k, v in (("invested_weeks", int(s.sum())), ("n_in_spells", len(lens(s, 1))), ("n_out_spells", len(lens(s, 0))), ("g_buy_weeks", int(g_used.sum())),
                     ("n_buy_spells", len(lens(g_used, 1))), ("n_sell_spells", len(lens(g_used, 0))), ("sessions_invested", si), ("sleeve_trades", ns)):
            diffs[k] = abs(v - int(r[k]))
            ok &= v == int(r[k])
        for c1, c2, x_ in (("in_lengths", "out_lengths", s), ("g_buy_lengths", "g_sell_lengths", g_used)):
            same = str(r[c1]) == "|".join(map(str, lens(x_, 1))) and str(r[c2]) == "|".join(map(str, lens(x_, 0)))
            diffs[c1 + "_strings_equal"] = same
            ok &= same
        print("stored draws.csv row found; differences (relative for the floats, absolute for the counts):", {k: (f"{v:.1e}" if isinstance(v, float) else v) for k, v in diffs.items()})
    else:
        print("no stored draws.csv row for these arguments")

    zp = ev / "draw_states.npz"
    if zp.exists():
        z = np.load(zp)
        sw = "full" if a.cash == "liq" else a.window
        for kind, typ, arr, rid in (("io", {"F1": "N4.10", "F2": "N4.9", "F5": "N4.10"}.get(fam), s, a.id), ("gold", {"F3": "N4.10-g", "F4": "N4.9-g", "F5": "N4.10-g"}.get(fam), g, gid if fam in ("F3", "F5") else a.id)):
            if typ is None:
                continue
            key = f"{a.book}|{sw}|{kind}|{typ}"
            if key in z.files and rid < z[key].shape[0]:
                found = True
                eq = bool(len(z[key][rid]) == len(arr) and (z[key][rid].astype(int) == arr).all())
                print(f"draw_states.npz[{key!r}][{rid}] equal to the rebuilt states: {eq}")
                ok &= eq
            else:
                print(f"draw_states.npz has no row for {key} id {rid}")
    cp = ev / "draw_curves_20.8.npz"
    if cp.exists() and a.window == "full" and a.cash == "lbes" and a.cost == 20.8 and a.sleeve_mode == "timed" and fam in ("F1", "F3"):
        z = np.load(cp)
        key = f"{a.book}|{fam}_{a.id}"
        if key in z.files:
            found = True
            c = z[key].astype(float)
            rel = float(np.abs(np.asarray(nav, dtype=float) / c - 1).max()) if len(c) == len(nav) else float("inf")
            print(f"draw_curves_20.8.npz[{key!r}]: maximum relative difference of the daily curve {rel:.1e} (float32 storage; need < 1e-6)")
            ok &= rel < 1e-6
    if not found:
        print("nothing in the evidence to compare with")
        sys.exit(2)
    print("EQUAL" if ok else "DIFFERENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
