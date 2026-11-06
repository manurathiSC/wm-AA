"""Reproduce one null draw from its id and compare it with the evidence.

    python tests/T06/rerun_draw.py --book SCMO_0003 --type N4.10 --id 17 --cost 20.8 [--window full|live] [--cash lbes|liquidcase]
    python tests/T06/rerun_draw.py --book SCMO_0003 --type N4.9  --id 445 --cost 20.8
    options: --run headline | --evidence DIR   (the evidence directory to compare with)

Uses the engine (analysis/t06_engine.py): rebuilds the draw's in-or-out series from its seed (N4.9: default_rng([3, id]), N4.10: default_rng([6, id])),
runs it through the same simulator and compares

  * every statistic with the row of evidence/<run>/draws.csv (end NAV, CAGR, drawdown, volatility, Ulcer index, days below -10%, longest time
    under water, Calmar, sessions, invested weeks, spell counts, the in- and out-lengths, sessions invested) to a relative 1e-12;
  * the rebuilt weekly states with the row of draw_states.npz (key "<book>|<window>|<type>"; LIQUIDCASE reuses the full-window states);
  * for the headline (full window, LBES, 20.8 bps) the daily curve with draw_curves_20.8.npz (float32, relative 1e-6).

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
import t06_engine as E  # noqa: E402  (the engine's interface: Book, simulate, stats, spells, spell_shuffle, rule_bounds, free_length_draw)

LIVE_START = pd.Timestamp("2021-11-01")  # T03's and the pre-registration's live window
LO = 2


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


def make_book(book, start, cash):
    if cash == "lbes":
        return E.Book(book, start=start, cash="lbes")
    last = None
    for name in ("liq", "liquidcase"):  # T03 called the desk's LIQUIDCASE leg "liq"; the interface of T06 only names "lbes"
        try:
            return E.Book(book, start=start, cash=name)
        except (ValueError, KeyError, AssertionError) as ex:
            last = ex
    raise SystemExit(f"cannot build a LIQUIDCASE book: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--type", choices=["N4.9", "N4.10"], required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--cost", type=float, default=20.8)
    ap.add_argument("--window", choices=["full", "live"], default="full")
    ap.add_argument("--cash", choices=["lbes", "liquidcase"], default="lbes")
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run

    bk = make_book(a.book, LIVE_START if a.window == "live" else None, a.cash)
    dec = bk.decisions()
    s = dec["state"].values.astype(int)
    # the bounds are the rule's longest spells on the FULL window, the same constants for every book and window
    full = E.Book(a.book).decisions()["state"].values.astype(int) if a.window == "live" else s
    hi_in, hi_out = E.rule_bounds(full)
    if a.type == "N4.9":
        st = E.spell_shuffle(s, a.id)
    else:
        st = E.free_length_draw(s, a.id, hi_in, hi_out, LO)
        st = st[0] if isinstance(st, tuple) else st
    st = np.asarray(st).astype(int)
    nav = E.simulate(bk, dec["decision_idx"].values, st.astype(float), a.cost)
    nav = nav[0] if isinstance(nav, tuple) else nav
    res = E.stats(nav)
    print("rebuilt:", {k: (round(v, 10) if isinstance(v, float) else v) for k, v in res.items()})
    print(f"bounds {LO}/{hi_in}/{hi_out}; weeks {len(st)}; invested {int(st.sum())}; in-lengths {lens(st, 1)}; out-lengths {lens(st, 0)}")

    ok, found = True, False
    d = pd.read_csv(ev / "draws.csv")
    row = d[(d.book == a.book) & (d.window == a.window) & (d.cash == a.cash) & (d.cost_bps == a.cost) & (d.draw_type == a.type) & (d.draw_id == a.id)]
    if len(row):
        found = True
        r = row.iloc[0]
        close = lambda x, y: abs(float(x) - float(y)) <= 1e-12 * max(1.0, abs(float(y)))
        diffs = {}
        for k in ("end_nav", "cagr", "max_dd", "vol", "ulcer", "calmar"):
            diffs[k] = abs(float(res[k]) - float(r[k])) / max(1.0, abs(float(r[k])))
            ok &= close(res[k], r[k])
        for k in ("days_below_10pct", "longest_underwater", "sessions"):
            diffs[k] = abs(int(res[k]) - int(r[k]))
            ok &= int(res[k]) == int(r[k])
        spells_in, spells_out = lens(st, 1), lens(st, 0)
        for k, v in (("invested_weeks", int(st.sum())), ("n_in_spells", len(spells_in)), ("n_out_spells", len(spells_out))):
            diffs[k] = abs(v - int(r[k]))
            ok &= v == int(r[k])
        if "in_lengths" in r and "out_lengths" in r:
            same = str(r.in_lengths) == "|".join(map(str, spells_in)) and str(r.out_lengths) == "|".join(map(str, spells_out))
            diffs["lengths_strings_equal"] = same
            ok &= same
        print("stored draws.csv row found; differences (relative for the floats, absolute for the counts):", {k: (f"{v:.1e}" if isinstance(v, float) else v) for k, v in diffs.items()})
    else:
        print("no stored draws.csv row for these arguments")

    zp = ev / "draw_states.npz"
    if zp.exists():
        z = np.load(zp)
        key = f"{a.book}|{'full' if a.cash == 'liquidcase' else a.window}|{a.type}"
        if key in z.files and a.id < z[key].shape[0]:
            found = True
            eq = bool(len(z[key][a.id]) == len(st) and (z[key][a.id].astype(int) == st).all())
            print(f"draw_states.npz[{key!r}][{a.id}] equal to the rebuilt states: {eq}")
            ok &= eq
        else:
            print(f"draw_states.npz has no row for {key} id {a.id}")
    cp = ev / "draw_curves_20.8.npz"
    if cp.exists() and a.window == "full" and a.cash == "lbes" and a.cost == 20.8:
        z = np.load(cp)
        key = f"{a.book}|{a.type}_{a.id}"
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
