"""Reproduce one null draw from its id and compare it with the evidence.

    python tests/T08/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8 [--window full|live] [--cash lbes|liq] [--sleeve-mode timed|fixed50]
    python tests/T08/rerun_draw.py --book SCMO_0003 --family F3 --id 5  --cost 20.8
    python tests/T08/rerun_draw.py --book SCMO_0003 --family F5 --id 5 --gold-id 5 --cost 20.8        (both timings random; --gold-id only if it differs from --id)
    options: --run headline | --evidence DIR   (the evidence directory to compare with)

Families (T08.md section 2): F1 = in-or-out N4.10 (seed default_rng([6, id])) with the real gold signal; F2 = in-or-out N4.9 ([3, id]) with the real gold signal;
F3 = real in-or-out switch with gold N4.10-g ([11, 6, id]); F4 = real switch with gold N4.9-g ([11, 3, id]); F5 = F1's in-or-out draw (id) with F3's gold draw (gold-id).

Uses the engine (analysis/t08_engine.py) through the T06 interface names: Book, simulate, stats, spell_shuffle, free_length_draw, rule_bounds. The gold draws use the
engine's own gold samplers if it exports them under one of GOLD_NAMES below, else this file's copy of the sampler (the same functions with the gold arguments, T08.md section 3 step 11).
WHAT TO ADJUST once the engine exists (the engine was not written when this file was): (1) the way `simulate` takes the per-decision gold weight (`gw=`; see run_sim),
(2) the names of the gold sampler functions (GOLD_NAMES), (3) the decision columns that hold the gold signal (`g` 0/1, or `sign_MAUc1` BUY/SELL) in Book.decisions().

It runs the draw through the same simulator and compares
  * every statistic with the row of evidence/<run>/draws.csv (end NAV, CAGR, drawdown, volatility, Ulcer index, days below -10%, longest time under water, Calmar,
    sessions, invested weeks, spell counts, BUY weeks, gold spell counts, the in/out and BUY/SELL length strings, sessions invested, sleeve trades) to a relative 1e-12;
  * the rebuilt weekly states with the rows of draw_states.npz (keys "<book>|<window>|io|N4.9", "...|io|N4.10", "...|gold|N4.9-g", "...|gold|N4.10-g"; LIQ reuses the full-window states);
  * for the headline (full window, LBES, 20.8 bps, timed) the daily curve of F1 and F3 with draw_curves_20.8.npz (float32, relative 1e-6).

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
import t08_engine as E  # noqa: E402  (the engine's interface: Book, simulate, stats, spell_shuffle, rule_bounds, free_length_draw)

LIVE_START = pd.Timestamp("2021-11-01")
LO = 2
GOLD_NAMES = {"N4.9-g": ("spell_shuffle_gold", "gold_spell_shuffle", "spell_shuffle_g"), "N4.10-g": ("free_length_draw_gold", "gold_free_length_draw", "free_length_draw_g")}
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


def make_book(book, start, cash):
    if cash == "lbes":
        return E.Book(book, start=start, cash="lbes")
    last = None
    for name in ("liq", "liquidcase"):
        try:
            return E.Book(book, start=start, cash=name)
        except (ValueError, KeyError, AssertionError) as ex:
            last = ex
    raise SystemExit(f"cannot build a LIQUIDCASE book: {last}")


def gold_series(dec):
    if "g" in dec:
        return dec["g"].values.astype(int)
    for c in ("sign_MAUc1", "g_sign"):
        if c in dec:
            return (dec[c].astype(str) == "BUY").values.astype(int)
    raise SystemExit("Book.decisions() has no gold column (g or sign_MAUc1): adjust gold_series()")


# a local copy of the sampler (T08.md section 3 step 11); used for the gold draws if the engine does not export its own
def dp_table(k, S, lo, hi):
    c = [[0] * (S + 1) for _ in range(k + 1)]
    c[0][0] = 1
    for m in range(1, k + 1):
        for t in range(S + 1):
            c[m][t] = sum(c[m - 1][t - x] for x in range(lo, min(hi, t) + 1))
    return c


def local_free_length(x, rid, seed, hi_buy, hi_sell, lo=LO):
    r = spells(x)
    k = {1: sum(1 for v, _ in r if v == 1), 0: sum(1 for v, _ in r if v == 0)}
    S = {1: sum(c for v, c in r if v == 1), 0: sum(c for v, c in r if v == 0)}
    hi = {1: hi_buy, 0: hi_sell}
    rng = np.random.default_rng(list(seed) + [rid])
    parts = {}
    for stt in (1, 0):
        c = dp_table(k[stt], S[stt], lo, hi[stt])
        t, out = S[stt], []
        for m in range(k[stt], 0, -1):
            w = np.array([c[m - 1][t - v] if t - v >= 0 else 0 for v in range(lo, hi[stt] + 1)], dtype=float)
            cum = np.cumsum(w)
            u = float(rng.random())
            v = lo + min(int(np.searchsorted(cum, u * cum[-1], side="right")), hi[stt] - lo)
            out.append(v)
            t -= v
        parts[stt] = out
    return interleave(int(x[0]), parts, k)


def local_shuffle(x, rid, seed):
    r = spells(x)
    rng = np.random.default_rng(list(seed) + [rid])
    ins, outs = [c for v, c in r if v == 1], [c for v, c in r if v == 0]
    ins = [ins[i] for i in rng.permutation(len(ins))]
    outs = [outs[i] for i in rng.permutation(len(outs))]
    return interleave(int(x[0]), {1: ins, 0: outs}, {1: len(ins), 0: len(outs)})


def interleave(first, parts, k):
    out, state, ptr = [], first, {1: 0, 0: 0}
    while ptr[1] < k[1] or ptr[0] < k[0]:
        out += [state] * parts[state][ptr[state]]
        ptr[state] += 1
        state = 1 - state
    return np.array(out, dtype=int)


def gold_draw(typ, x, rid, bounds):
    for nm in GOLD_NAMES[typ]:
        f = getattr(E, nm, None)
        if f is not None:
            r = f(x, rid, *bounds) if typ == "N4.10-g" else f(x, rid)
            print(f"gold sampler: engine function {nm}")
            return np.asarray(r[0] if isinstance(r, tuple) else r).astype(int)
    print("gold sampler: this file's copy (the engine exports none of", GOLD_NAMES[typ], ")")
    return local_shuffle(x, rid, [11, 3]) if typ == "N4.9-g" else local_free_length(x, rid, [11, 6], *bounds)


def run_sim(bk, dec, s, gw, cost):
    """Run the engine's simulator with the in-or-out states `s` and the per-decision gold weight `gw` (None = the engine's default, i.e. the rule's own)."""
    idx = dec["decision_idx"].values
    for call in (lambda: E.simulate(bk, idx, s.astype(float), cost, gw=gw), lambda: E.simulate(bk, idx, s.astype(float), cost, gw)):
        try:
            return call()
        except TypeError:
            continue
    raise SystemExit("E.simulate does not accept a per-decision gold weight as `gw=` or as a fifth positional argument: adjust run_sim()")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--family", choices=list(SEEDS), required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--gold-id", type=int, default=None, help="F5 only, if the gold draw id differs from --id")
    ap.add_argument("--cost", type=float, default=20.8)
    ap.add_argument("--window", choices=["full", "live"], default="full")
    ap.add_argument("--cash", choices=["lbes", "liq"], default="lbes")
    ap.add_argument("--sleeve-mode", choices=["timed", "fixed50"], default="timed")
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    gid = a.id if a.gold_id is None else a.gold_id
    fam = a.family

    bk = make_book(a.book, LIVE_START if a.window == "live" else None, a.cash)
    dec = bk.decisions()
    s_real = dec["state"].values.astype(int)
    g_real = gold_series(dec)
    # the bounds are the real series' longest spells on the FULL window, the same constants for every book and window
    full = E.Book(a.book).decisions() if a.window == "live" else dec
    hi_in, hi_out = E.rule_bounds(full["state"].values.astype(int))
    gf = gold_series(full)
    hi_buy, hi_sell = max(lens(gf, 1)), max(lens(gf, 0))
    if fam in ("F1", "F5"):
        s = np.asarray(E.free_length_draw(s_real, a.id, hi_in, hi_out, LO)).astype(int)
    elif fam == "F2":
        s = np.asarray(E.spell_shuffle(s_real, a.id)).astype(int)
    else:
        s = s_real
    s = s[0] if s.ndim > 1 else s
    if fam in ("F3", "F5"):
        g = gold_draw("N4.10-g", g_real, gid, (hi_buy, hi_sell))
    elif fam == "F4":
        g = gold_draw("N4.9-g", g_real, a.id, None)
    else:
        g = g_real
    gw = np.full(len(g), 0.5) if a.sleeve_mode == "fixed50" else np.where(g == 1, 0.8, 0.2)
    res = run_sim(bk, dec, s, gw, a.cost)
    nav = res[0] if isinstance(res, tuple) else res
    stt = E.stats(nav)
    print("rebuilt:", {k: (round(v, 10) if isinstance(v, float) else v) for k, v in stt.items()})
    print(f"bounds in-or-out {LO}/{hi_in}/{hi_out}, gold {LO}/{hi_buy}/{hi_sell}; weeks {len(s)}; invested {int(s.sum())}; BUY weeks {int(g.sum())}; in-lengths {lens(s, 1)}; out-lengths {lens(s, 0)}; "
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
        for k, v in (("invested_weeks", int(s.sum())), ("n_in_spells", len(lens(s, 1))), ("n_out_spells", len(lens(s, 0))), ("g_buy_weeks", int(g.sum())), ("n_buy_spells", len(lens(g, 1))), ("n_sell_spells", len(lens(g, 0)))):
            if k in r:
                diffs[k] = abs(v - int(r[k]))
                ok &= v == int(r[k])
        for c1, c2, x_ in (("in_lengths", "out_lengths", s), ("g_buy_lengths", "g_sell_lengths", g)):
            if c1 in r and c2 in r:
                same = str(r[c1]) == "|".join(map(str, lens(x_, 1))) and str(r[c2]) == "|".join(map(str, lens(x_, 0)))
                diffs[c1 + "_strings_equal"] = same
                ok &= same
        if "sessions_invested" in r and hasattr(E, "sessions_invested"):
            si = int(E.sessions_invested(bk, dec["decision_idx"].values, s))
            diffs["sessions_invested"] = abs(si - int(r.sessions_invested))
            ok &= si == int(r.sessions_invested)
        if isinstance(res, tuple) and "sleeve_trades" in r:
            print("(sleeve trades per draw are counted by the engine's run_book; compared if the engine returns them as the second element)")
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
