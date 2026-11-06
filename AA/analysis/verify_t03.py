"""T03 independent verifier (Step 4).

Re-derives T03's decisions, NAVs, costs, trades and null draws from the RAW files
only (plain numpy / pandas, its own loaders, its own cost and basket logic) and
compares them with the engine's evidence in tests/T03/evidence/headline/.

It imports nothing from the engine or from any other module in analysis/ or data/.
It never reads the engine's source. The rules are those of tests/T03/logs/verifier_spec.md.

Usage (from AA/):
    python analysis/verify_t03.py                         # real run + self-test on a corrupted copy
    python analysis/verify_t03.py --evidence DIR --no-selftest   # compare against another evidence dir

Exit code 0 only if rows were compared, none failed, none were missing, and (in the
default run) the deliberately corrupted copy was detected.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
END = pd.Timestamp("2026-08-21")
ALWAYS_IN_END = pd.Timestamp("2026-10-22")
COSTS = [0.0, 20.8, 50.0]
TOL = 1e-9
N_DRAWS = 2000
SCRATCH = Path(r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\9eaaf486-295a-41b5-9378-c07664070b83\scratchpad")


# ----------------------------------------------------------------------------------------
# raw loaders
# ----------------------------------------------------------------------------------------
def load_published_nav(p):
    d = pd.read_csv(AA / "Historical Data" / "parent_nav_2026-10-22" / f"{p}.csv")
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_masters():
    out = {}
    for name in ["Nifty100", "MC100", "SC100"]:
        m = pd.read_excel(AA / "Historical Data" / "frozen_2026-09-25" / "Master" / f"Master_{name}.xlsx")
        m = m[["Date", "SIGN"]].copy()
        m["SIGN"] = m["SIGN"].astype("object")
        m = m[m["SIGN"].notna()]
        m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
        m = m[m["SIGN"] != ""]
        m["Date"] = pd.to_datetime(m["Date"])
        m = m.sort_values("Date").reset_index(drop=True)
        out[name] = (m["Date"].values, m["SIGN"].values)
    return out


def load_gold():
    g = pd.read_parquet(AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet")
    g = g[["date", "open", "high", "low", "close"]].copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    g = g.set_index("date").sort_index()
    m = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv")
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.set_index("date").sort_index()
    return g, m


def despiked_goldbees_fill(g, m):
    """Rule 3. Returns (fill, close) indexed by GOLDBEES bar dates."""
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + 0.005
    lo = g["close"] * (1 - band)
    hi = g["close"] * (1 + band)
    o2 = g["open"].clip(lower=lo, upper=hi)
    h2 = np.minimum(g["high"], hi)
    l2 = np.maximum(g["low"], lo)
    h2 = np.maximum(np.maximum(h2, o2), g["close"])
    l2 = np.minimum(np.minimum(l2, o2), g["close"])
    have = rng.notna()
    o_ = g["open"].where(~have, o2)
    h_ = g["high"].where(~have, h2)
    l_ = g["low"].where(~have, l2)
    fill = (o_ + h_ + l_ + g["close"]) / 4.0
    return fill, g["close"]


def load_lbes():
    d = pd.read_csv(AA / "Historical Data" / "LBES_Adjusted_Price_data_2026_08_10.csv")
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y %H:%M").dt.normalize()
    return d.set_index("date")["price"].sort_index()


def cash_levels(cal, lbes):
    """Rule 4. cal = full calendar (DatetimeIndex)."""
    last = lbes.index[-1]
    asof = lbes.reindex(cal, method="ffill")
    L = asof.values.astype(float).copy()
    s = int(np.searchsorted(cal.values, np.datetime64(last), side="right") - 1)  # last session on or before the file's last date
    r = (asof.values[s] / asof.values[s - 90]) ** (1.0 / 90.0) - 1.0
    L_last = float(lbes.iloc[-1])
    after = np.where(cal.values > np.datetime64(last))[0]
    for k, i in enumerate(after, start=1):
        L[i] = L_last * (1.0 + r) ** k
    return L, dict(file_last=str(last.date()), daily_rate=float(r), accrued_sessions=int(np.sum(cal.values[after] <= np.datetime64(END))), s_date=str(cal[s].date()))


def load_corrections():
    c = pd.read_csv(AA / "data" / "holdings_matrix" / "price_corrections.csv")
    c["ex_date"] = pd.to_datetime(c["ex_date"])
    return c


def load_book_prices(p, corr):
    """Stock OHLC for the book with the price correction applied.
    Returns wide frames indexed by D18 date: close_ffill (rule 2), fill (OHLC4 rules), orig_close_notna."""
    o = pd.read_csv(AA / "data" / "holdings_matrix" / f"{p}_ohlc.csv", usecols=["date", "stock", "open", "high", "low", "close"])
    o["date"] = pd.to_datetime(o["date"])
    for _, r in corr.iterrows():
        books = [x.strip() for x in str(r["applies_to"]).replace(";", ",").split(",")]
        if p in books:
            msk = (o["stock"] == r["stock"]) & (o["date"] < r["ex_date"])
            for c in ["open", "high", "low", "close"]:
                o.loc[msk, c] = o.loc[msk, c] * float(r["factor"])
    o = o[o["close"].notna()]
    d18 = pd.DatetimeIndex(sorted(o["date"].unique()))
    W = {c: o.pivot(index="date", columns="stock", values=c).reindex(d18) for c in ["open", "high", "low", "close"]}
    close_ff = W["close"].ffill()
    ohlc4 = (W["open"] + W["high"] + W["low"] + W["close"]) / 4.0
    all4 = W["open"].notna() & W["high"].notna() & W["low"].notna() & W["close"].notna()
    bar = W["close"].notna()
    fill = ohlc4.where(all4, W["close"])        # a blank open/high/low -> the close
    fill = fill.where(bar, close_ff)             # no bar that session -> the last close
    return d18, close_ff, fill


def load_baskets(p):
    """Rule 12 row 4: rows = availableDate, drop csv_only_skipped, renormalise."""
    m = pd.read_csv(AA / "data" / "holdings_matrix" / f"{p}_holding_weight_matrix.csv")
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    s = pd.read_csv(AA / "data" / "holdings_matrix" / f"{p}_holding_weight_sources.csv")
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    dropped = sorted(skipped)
    m = m[~m["avail"].isin(skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    W = m[cols].fillna(0.0).values.astype(float)
    W = W / W.sum(axis=1, keepdims=True)
    return m["avail"].values, cols, W, [str(pd.Timestamp(x).date()) for x in dropped]


# ----------------------------------------------------------------------------------------
# book construction
# ----------------------------------------------------------------------------------------
def build_book(p, masters, gold_fill, gold_close, lbes, corr):
    nav = load_published_nav(p)
    t0 = nav.index[0]
    cal_full = nav.index[nav.index >= t0]              # D17 dates (to 2026-10-22), rule 1
    end_idx = int(np.searchsorted(cal_full.values, np.datetime64(END), side="right"))  # number of sessions in window
    n_full = len(cal_full)

    d18, close_ff, fill = load_book_prices(p, corr)
    avail, cols, Wm, dropped = load_baskets(p)
    # stocks that ever carry weight in a basket we may use
    S_cols = [c for c, any_ in zip(cols, (Wm > 0).any(axis=0)) if any_]
    ci = [cols.index(c) for c in S_cols]
    Wm = Wm[:, ci]
    missing_cols = [c for c in S_cols if c not in close_ff.columns]
    assert not missing_cols, (p, missing_cols)
    Cff = close_ff[S_cols]
    Ffl = fill[S_cols]
    miss_dates = [d for d in cal_full if d not in Cff.index]
    assert not miss_dates, (p, miss_dates[:3])
    C = Cff.reindex(cal_full).values
    F = Ffl.reindex(cal_full).values
    Cn = np.nan_to_num(C, nan=0.0)

    # GOLDBEES (rule 3)
    gclose = gold_close.reindex(cal_full, method="ffill").values
    gfill = gold_fill.reindex(cal_full).values
    gfill = np.where(np.isnan(gfill), gclose, gfill)
    L, cash_info = cash_levels(cal_full, lbes)

    # baskets (rule 6): effect = first calendar session on or after availableDate
    eff = np.searchsorted(cal_full.values, avail, side="left")
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n_full:
            basket_at[int(eff[k])] = k           # a later availableDate with the same effect session overrides
    b_idx = sorted(basket_at)
    in_force_t0_key = max(k for k in b_idx if k <= 0)
    k0 = basket_at[in_force_t0_key]
    first_d18 = d18[np.searchsorted(d18.values, avail[k0], side="left")]
    init_fill = Ffl.loc[first_d18].values
    # list of changes after T0
    changes = [i for i in b_idx if 0 < i < n_full]
    return dict(p=p, t0=t0, cal=cal_full, n_win=end_idx, n_full=n_full, S=S_cols, C=C, Cn=Cn, F=F,
                gc=gclose, gf=gfill, L=L, cash=cash_info, W=Wm, basket_at=basket_at, b_idx=b_idx, changes=changes,
                k0=k0, init_fill=init_fill, avail=avail, first_d18=first_d18, dropped=dropped, pub=nav)


def decisions_for_book(B, masters):
    """Rules 5. Returns DataFrame in the evidence column layout (without comparison)."""
    cal = B["cal"][: B["n_win"]]
    t0 = cal[0]
    iso = cal.isocalendar()
    key = iso["year"].astype(int).values * 100 + iso["week"].astype(int).values
    df = pd.DataFrame({"date": cal, "key": key, "idx": np.arange(len(cal))})
    last = df.groupby("key").tail(1)
    last = last[last["date"] > t0]
    dec_idx = np.concatenate([[0], last["idx"].values])
    dec_idx = np.array(sorted(set(dec_idx.tolist())))
    rows = []
    names = ["Nifty100", "MC100", "SC100"]
    for j, ix in enumerate(dec_idx):
        d = cal[ix]
        signs, labels = [], []
        for nm in names:
            dates, sg = masters[nm]
            pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
            signs.append(sg[pos]); labels.append(pd.Timestamp(dates[pos]))
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        rows.append(dict(book=B["p"], j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the simulation (rules 7-9, 11)
# ----------------------------------------------------------------------------------------
def simulate(B, states, bps, dec_idx, n, mix_f=None, mix_first=True, e_fixed=None):
    """Run one realisation on the first n sessions of B's calendar.

    states   : array of decision states s_0..s_n (0/1)
    mix_f    : constant mix comparator (e = f, rebalance at every decision's next session and every basket change)
    Returns dict(nav, trades, units snapshots info, closed-form diagnostics)."""
    C, Cn, F = B["C"], B["Cn"], B["F"]
    gc, gf, L = B["gc"], B["gf"], B["L"]
    S = len(B["S"])
    b_idx = B["b_idx"]
    W = B["W"]
    D = len(states)

    def basket_key(i):
        # latest basket with effect on or before i
        pos = np.searchsorted(b_idx, i, side="right") - 1
        return b_idx[pos]

    # initial position at T0 close (rule 7), no cost
    basket_at = B["basket_at"]
    k0 = B["k0"]
    w0 = W[k0]
    sh0 = np.where(w0 > 0, w0 / B["init_fill"], 0.0)
    sh0 = sh0 / float((sh0 * Cn[0]).sum())
    if mix_f is not None:
        e = float(mix_f)
    elif e_fixed is not None:
        e = float(e_fixed)
    else:
        e = float(states[0])
    shares = sh0 * e if e > 0 else np.zeros(S)
    if mix_f is not None:
        shares = sh0 * e   # drifted basket scaled to a share f of NAV 1
    gu = (1 - e) / 2.0 / gc[0]
    cu = (1 - e) / 2.0 / L[0]
    if e > 0 and mix_f is None and e_fixed is None:
        assert abs(e - 1.0) < 1e-15

    # events
    sw = {}
    if mix_f is not None:
        start = 0 if mix_first else 1
        for j in range(start, D - 1):
            sw[int(dec_idx[j]) + 1] = float(mix_f)
    else:
        for j in range(1, D - 1):
            if states[j] != states[j - 1]:
                sw[int(dec_idx[j]) + 1] = float(states[j])
    chg = [i for i in B["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = []      # (start_idx, shares, gu, cu)
    trades = []
    segs.append((0, shares.copy(), gu, cu))
    for i in events:
        w = W[basket_at[basket_key(i)]]
        pf = F[i]
        if i in sw:
            e_new = sw[i]
            if mix_f is not None:
                kind = "mix_rebalance"
            else:
                kind = "switch_in" if e_new == 1.0 else "switch_out"
        else:
            e_new = e
            kind = "basket_change"
            if e <= 0.0:
                continue      # basket change while OUT: nothing traded
        held = shares != 0
        if np.isnan(pf[(w > 0) | held]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {B['cal'][i]}")
        cur_stock = np.where(held, shares * np.where(np.isnan(pf), 0.0, pf), 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        V = cur_stock.sum() + cur_g + cur_c
        tgt_stock = e_new * V * w
        tgt_g = (1 - e_new) / 2.0 * V
        tgt_c = (1 - e_new) / 2.0 * V
        traded = np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c)
        cost = traded * bps / 2.0 / 10000.0
        f = (V - cost) / V
        shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        e = e_new
        segs.append((i, shares.copy(), gu, cu))
        trades.append(dict(idx=i, date=str(B["cal"][i].date()), kind=kind, e_after=e, basket_eff=str(B["cal"][basket_key(i)].date()),
                           V=V, traded=traded, cost=cost))

    # NAV with units after any trade on the session (rule 9) + closed-form segment product
    nav = np.empty(n)
    seg_end = [s[0] for s in segs[1:]] + [n]
    closed_max_rel = 0.0
    prod = 1.0
    prev_end_val = None
    for (i0, sh, gu_, cu_), i1 in zip(segs, seg_end):
        nz = sh != 0
        if np.isnan(C[i0:i1][:, nz]).any():
            raise RuntimeError("held stock without a close")
        v = Cn[i0:i1] @ sh + gc[i0:i1] * gu_ + L[i0:i1] * cu_
        nav[i0:i1] = v
        # closed form: units are fixed, so NAV_t = NAV_start * prod of daily growth factors
        growth = np.empty(len(v)); growth[0] = 1.0
        if len(v) > 1:
            growth[1:] = v[1:] / v[:-1]
        recon = v[0] * np.cumprod(growth)
        closed_max_rel = max(closed_max_rel, float(np.max(np.abs(recon - v) / np.abs(v))))
        # jump factor on the trade day times the segment growth
        jump = 1.0 if prev_end_val is None else v[0] / prev_end_val
        prod *= jump * (v[-1] / v[0])
        prev_end_val = v[-1]
    end_from_segments = prod                  # NAV_0 = 1: product of (jump x segment growth)
    return dict(nav=nav, trades=trades, closed_rel=closed_max_rel, n_segments=len(segs),
                end_from_segments=end_from_segments)


def stats_of(nav):
    n = len(nav)
    years = (n - 1) / 252.0
    cagr = nav[-1] ** (1.0 / years) - 1.0
    peak = np.maximum.accumulate(nav)
    mdd = float(np.min(nav / peak - 1.0))
    ret = nav[1:] / nav[:-1] - 1.0
    vol = float(np.std(ret, ddof=1) * np.sqrt(252.0))
    return dict(end_nav=float(nav[-1]), cagr=float(cagr), max_dd=mdd, vol=vol, sessions=n)


# ----------------------------------------------------------------------------------------
# null draws (rule 12)
# ----------------------------------------------------------------------------------------
def runs_of(s):
    out = []
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[start]:
            out.append((int(s[start]), i - start))
            start = i
    return out


def n49_states(s, draw_id):
    runs = runs_of(s)
    ins = [l for v, l in runs if v == 1]
    outs = [l for v, l in runs if v == 0]
    rng = np.random.default_rng([3, draw_id])
    pi = rng.permutation(len(ins))
    po = rng.permutation(len(outs))
    ins2 = [ins[k] for k in pi]
    outs2 = [outs[k] for k in po]
    cur = int(s[0])
    ii = oo = 0
    out = []
    for r in range(len(runs)):
        st = cur if r % 2 == 0 else 1 - cur
        if st == 1:
            out.extend([1] * ins2[ii]); ii += 1
        else:
            out.extend([0] * outs2[oo]); oo += 1
    return np.array(out, dtype=int)


def spell_summary(s):
    runs = runs_of(s)
    ins = sorted(l for v, l in runs if v == 1)
    outs = sorted(l for v, l in runs if v == 0)
    return int(np.sum(s)), len(ins), len(outs), ins, outs


# ----------------------------------------------------------------------------------------
# comparison machinery
# ----------------------------------------------------------------------------------------
class Check:
    def __init__(self, name, gate=True):
        self.name = name
        self.compared = 0
        self.failed = 0
        self.missing = 0
        self.worst_rel = 0.0
        self.first_fail = None
        self.gate = gate
        self.notes = []

    def fail(self, desc):
        if self.first_fail is None:
            self.first_fail = desc

    def to_dict(self):
        return dict(compared=int(self.compared), failed=int(self.failed), missing=int(self.missing),
                    worst_rel=float(self.worst_rel), first_fail=self.first_fail, gate=self.gate, notes=self.notes)


def rel(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return np.abs(a - b) / np.maximum(np.abs(b), 1e-12)


def compare_frames(chk, mine, ev, keys, num_cols=(), str_cols=(), tol=TOL):
    """Outer-join on keys; rows present on both sides are compared; others are 'missing'."""
    m = mine.merge(ev, on=keys, how="outer", suffixes=("_v", "_e"), indicator=True)
    both = m[m["_merge"] == "both"]
    miss = m[m["_merge"] != "both"]
    chk.missing += len(miss)
    if len(miss):
        r = miss.iloc[0]
        chk.fail("missing row (%s): %s" % ("verifier only" if r["_merge"] == "left_only" else "evidence only", {k: r[k] for k in keys}))
    bad = np.zeros(len(both), dtype=bool)
    first_desc = None
    for c in num_cols:
        a = both[c + "_v"].astype(float).values
        b = both[c + "_e"].astype(float).values
        nanmis = np.isnan(a) != np.isnan(b)
        r = np.where(np.isnan(a) & np.isnan(b), 0.0, rel(a, b))
        r = np.where(nanmis, np.inf, r)
        fin = r[np.isfinite(r)]
        if len(fin):
            chk.worst_rel = max(chk.worst_rel, float(fin.max()))
        bc = r > tol
        if bc.any() and first_desc is None:
            i = int(np.argmax(bc))
            first_desc = "first differing row %s col %s: verifier=%r evidence=%r" % ({k: both.iloc[i][k] for k in keys}, c, a[i], b[i])
        bad |= bc
    for c in str_cols:
        a = both[c + "_v"].astype(object).where(both[c + "_v"].notna(), "<NA>").astype(str).values
        b = both[c + "_e"].astype(object).where(both[c + "_e"].notna(), "<NA>").astype(str).values
        bc = a != b
        if bc.any() and first_desc is None:
            i = int(np.argmax(bc))
            first_desc = "first differing row %s col %s: verifier=%r evidence=%r" % ({k: both.iloc[i][k] for k in keys}, c, a[i], b[i])
        bad |= bc
    chk.compared += len(both)
    chk.failed += int(bad.sum())
    if first_desc:
        chk.fail(first_desc)


# ----------------------------------------------------------------------------------------
# derive everything (once), compare against any evidence directory
# ----------------------------------------------------------------------------------------
def derive():
    t = time.time()
    masters = load_masters()
    g, mcx = load_gold()
    gfill, gclose = despiked_goldbees_fill(g, mcx)
    lbes = load_lbes()
    corr = load_corrections()
    D = {"books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "sample_draws": [], "all_draws": [], "always_in": [],
         "draw_states": [], "meta": {}}
    rng_pick = np.random.default_rng(20261105)
    for p in BOOKS:
        B = build_book(p, masters, gfill, gclose, lbes, corr)
        print(f"[{time.time()-t:6.1f}s] {p}: built (sessions in window {B['n_win']}, stocks {len(B['S'])}, baskets {len(B['b_idx'])})", flush=True)
        dec = decisions_for_book(B, masters)
        D["dec"].append(dec)
        n = B["n_win"]
        cal = B["cal"][:n]
        dec_idx = dec["decision_idx"].values
        s = dec["state"].values.astype(int)
        nd = len(s)
        f_mix = s.sum() / nd
        meta = dict(sessions=n, decisions=nd, invested_weeks=int(s.sum()), t0=str(cal[0].date()),
                    stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()),
                    initial_basket_switch_session=str(B["first_d18"].date()), cash=B["cash"], dropped=B["dropped"],
                    in_spells=len([1 for v, l in runs_of(s) if v == 1]), out_spells=len([1 for v, l in runs_of(s) if v == 0]),
                    f=f_mix)
        D["meta"][p] = meta
        base_sum = spell_summary(s)
        # --- strategy at 3 costs + comparators
        for bps in COSTS:
            runs = {
                "strategy": simulate(B, s, bps, dec_idx, n),
                "hold_parent": simulate(B, np.ones(nd, dtype=int), bps, dec_idx, n),
                "sleeve_only": simulate(B, np.zeros(nd, dtype=int), bps, dec_idx, n),
                "constant_mix": simulate(B, s, bps, dec_idx, n, mix_f=f_mix, mix_first=True),
                "constant_mix_nofirst": simulate(B, s, bps, dec_idx, n, mix_f=f_mix, mix_first=False),
            }
            for kind, r in runs.items():
                st = stats_of(r["nav"])
                st.update(book=p, cost_bps=bps, kind=kind, trades=len(r["trades"]),
                          cost_paid=float(sum(x["cost"] for x in r["trades"])),
                          closed_rel=r["closed_rel"], n_segments=r["n_segments"],
                          end_from_segments=r["end_from_segments"])
                D["stats"].append(st)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
                for x in r["trades"]:
                    D["trades"].append(dict(book=p, cost_bps=bps, run=kind, **x))
        # --- null draws at 20.8 bps: sample
        ids = list(range(20)) + sorted(rng_pick.choice(np.arange(20, N_DRAWS), size=20, replace=False).tolist())
        for did in ids:
            ds = n49_states(s, did)
            r = simulate(B, ds, 20.8, dec_idx, n)
            st = stats_of(r["nav"])
            D["sample_draws"].append(dict(book=p, draw_type="N4.9", draw_id=did, **{k: st[k] for k in ["end_nav", "cagr", "max_dd"]}))
        ks = np.arange(46, nd - 46 + 1)   # 46 <= k <= n-46, n = nd-1
        ks = np.arange(46, (nd - 1) - 46 + 1)
        for k in sorted(rng_pick.choice(ks, size=10, replace=False).tolist()):
            ds = np.roll(s, int(k))
            r = simulate(B, ds, 20.8, dec_idx, n)
            st = stats_of(r["nav"])
            D["sample_draws"].append(dict(book=p, draw_type="shift", draw_id=int(k), **{k2: st[k2] for k2 in ["end_nav", "cagr", "max_dd"]}))
        # --- all draws: spells (no NAV needed)
        for did in range(N_DRAWS):
            ds = n49_states(s, did)
            iw, nin, nout, ins, outs = spell_summary(ds)
            same = (iw == base_sum[0] and nin == base_sum[1] and nout == base_sum[2] and ins == base_sum[3] and outs == base_sum[4])
            D["all_draws"].append(dict(book=p, draw_id=did, invested_weeks=iw, n_in_spells=nin, n_out_spells=nout, sorted_same=bool(same)))
            if did < 3:
                for j in range(nd):
                    D["draw_states"].append(dict(book=p, draw_id=did, j=j, decision_date=dec["decision_date"].iloc[j],
                                                 real_state=int(s[j]), draw_state=int(ds[j])))
        # --- always-in to 2026-10-22 against the published NAV
        nfull = B["n_full"]
        r = simulate(B, np.ones(nd, dtype=int), 0.0, dec_idx, nfull)
        nav_m = pd.Series(r["nav"], index=B["cal"])
        pub = B["pub"].loc[B["cal"]]
        pub = pub / pub.iloc[0]
        yrs = (len(nav_m) - 1) / 252.0
        cg_m = nav_m.iloc[-1] ** (1 / yrs) - 1
        cg_p = pub.iloc[-1] ** (1 / yrs) - 1
        rows = [dict(book=p, scope="overall", gap_pp=float((cg_m - cg_p) * 100), limit_pp=0.25)]
        ye_m = nav_m.groupby(nav_m.index.year).last()
        ye_p = pub.groupby(pub.index.year).last()
        ym = ye_m / ye_m.shift(1).fillna(1.0) - 1
        yp = ye_p / ye_p.shift(1).fillna(1.0) - 1
        for y in ym.index:
            rows.append(dict(book=p, scope=str(y), gap_pp=float((ym[y] - yp[y]) * 100), limit_pp=0.5))
        D["always_in"].extend(rows)
        D["meta"][p]["always_in_end"] = str(B["cal"][-1].date())
        print(f"[{time.time()-t:6.1f}s] {p}: done (f={f_mix:.4f}, always-in CAGR gap {rows[0]['gap_pp']:+.3f} pp)", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["sample_draws"] = pd.DataFrame(D["sample_draws"])
    D["all_draws"] = pd.DataFrame(D["all_draws"])
    D["always_in"] = pd.DataFrame(D["always_in"])
    D["draw_states"] = pd.DataFrame(D["draw_states"])
    return D


def load_evidence(evdir):
    E = {}
    E["dec"] = pd.read_csv(evdir / "decisions.csv")
    E["stats"] = pd.read_csv(evdir / "stats.csv")
    E["draws"] = pd.read_csv(evdir / "draws.csv")
    E["trades"] = pd.read_csv(evdir / "trades.csv")
    E["nav"] = pd.read_csv(evdir / "daily_nav.csv")
    E["audit"] = json.load(open(evdir / "audit.json"))
    ds = evdir / "draw_states_example.csv"
    E["draw_states"] = pd.read_csv(ds) if ds.exists() else None
    return E


def r4(x):
    return np.round(x.astype(float), 4)


def compare_all(D, E):
    C = {}

    # ---- C-dec ----
    c = Check("C-dec"); C[c.name] = c
    cols_s = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100",
              "latest_label", "decision_date", "all_three_buy", "state"]
    ev = E["dec"].copy()
    ev["all_three_buy"] = ev["all_three_buy"].astype(str)
    mine = D["dec"].copy()
    mine["all_three_buy"] = mine["all_three_buy"].astype(str)
    compare_frames(c, mine, ev, ["book", "j"], num_cols=["decision_idx", "label_age_days", "state"],
                   str_cols=[x for x in cols_s if x != "state"])

    # ---- C-pit ----
    c = Check("C-pit"); C[c.name] = c
    ev = E["dec"]
    for lc in ["label_Nifty100", "label_MC100", "label_SC100"]:
        ok = (ev[lc].astype(str) <= ev["decision_date"].astype(str)).values
        c.compared += len(ev); c.failed += int((~ok).sum())
        if (~ok).any(): c.fail("label after decision date: %s" % ev[~ok].iloc[0][["book", "j", "decision_date", lc]].to_dict())
    tdm = ev["trade_date"].notna()
    ok = (ev.loc[tdm, "trade_date"].astype(str) > ev.loc[tdm, "decision_date"].astype(str)).values
    c.compared += int(tdm.sum()); c.failed += int((~ok).sum())
    if (~ok).any(): c.fail("trade not after decision: %s" % ev.loc[tdm][~ok].iloc[0][["book", "j", "decision_date", "trade_date"]].to_dict())
    # every switch trade in trades.csv sits on a decision's trade date and after its decision date
    tr = E["trades"]
    sw = tr[(tr["run"] == "strategy") & tr["kind"].isin(["switch_in", "switch_out"])]
    mm = sw.merge(ev[["book", "trade_date", "decision_date"]], left_on=["book", "date"], right_on=["book", "trade_date"], how="left")
    okk = mm["decision_date"].notna() & (mm["date"].astype(str) > mm["decision_date"].astype(str))
    c.compared += len(mm); c.failed += int((~okk).sum())
    if (~okk).any(): c.fail("switch trade without an earlier decision: %s" % mm[~okk].iloc[0][["book", "date"]].to_dict())
    # also the verifier's own derivation must satisfy it
    md = D["dec"]
    for lc in ["label_Nifty100", "label_MC100", "label_SC100"]:
        ok = (md[lc] <= md["decision_date"]).values
        c.compared += len(md); c.failed += int((~ok).sum())
    mt = md["trade_date"].notna()
    ok = (md.loc[mt, "trade_date"] > md.loc[mt, "decision_date"]).values
    c.compared += int(mt.sum()); c.failed += int((~ok).sum())

    # ---- stats-based and NAV-based checks ----
    est = E["stats"]
    est = est[(est["window"] == "full") & (est["cash"] == "lbes")].copy()
    est["cost_bps"] = r4(est["cost_bps"])
    mst = D["stats"].copy()
    mst["cost_bps"] = r4(mst["cost_bps"])
    env = E["nav"].copy()
    env["cost_bps"] = r4(env["cost_bps"])
    mnv = D["nav"].copy()
    mnv["cost_bps"] = r4(mnv["cost_bps"])
    env["date"] = env["date"].astype(str)

    def nav_subset(df, kinds, costs):
        return df[df["run"].isin(kinds) & df["cost_bps"].isin(costs)]

    def stat_subset(df, kinds, costs):
        return df[df["kind"].isin(kinds) & df["cost_bps"].isin(costs)]

    # C-nav0
    c = Check("C-nav0"); C[c.name] = c
    compare_frames(c, nav_subset(mnv, ["strategy"], [0.0]), nav_subset(env, ["strategy"], [0.0]), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    compare_frames(c, stat_subset(mst, ["strategy"], [0.0])[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                   stat_subset(est, ["strategy"], [0.0])[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                   ["book", "cost_bps", "kind"], num_cols=["end_nav", "cagr", "max_dd", "vol"])
    # closed form: product of (trade-day jump x segment growth) = end NAV, and segment cumprod = NAV, own check vs own NAV
    c2 = Check("C-nav0-closed-form"); C[c2.name] = c2
    for st in D["stats"].itertuples():
        if st.kind != "strategy":
            continue
        r_ = abs(st.end_from_segments - st.end_nav) / st.end_nav
        c2.compared += 1
        c2.worst_rel = max(c2.worst_rel, r_, st.closed_rel)
        if r_ > TOL or st.closed_rel > TOL:
            c2.failed += 1; c2.fail(f"{st.book} cost {st.cost_bps}: segment product {st.end_from_segments!r} vs NAV {st.end_nav!r}, within-segment rel {st.closed_rel:.2e}")
        # and against the engine's end NAV
        e_ = est[(est["book"] == st.book) & (est["cost_bps"] == round(st.cost_bps, 4)) & (est["kind"] == "strategy")]
        if len(e_):
            c2.compared += 1
            rr = abs(st.end_from_segments - float(e_["end_nav"].iloc[0])) / float(e_["end_nav"].iloc[0])
            c2.worst_rel = max(c2.worst_rel, rr)
            if rr > TOL:
                c2.failed += 1; c2.fail(f"{st.book} cost {st.cost_bps}: closed-form end NAV vs evidence end_nav rel {rr:.2e}")
        else:
            c2.missing += 1; c2.fail(f"evidence strategy stats row missing for {st.book} {st.cost_bps}")

    # C-cost
    c = Check("C-cost"); C[c.name] = c
    compare_frames(c, stat_subset(mst, ["strategy"], [20.8, 50.0])[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                   stat_subset(est, ["strategy"], [20.8, 50.0])[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                   ["book", "cost_bps", "kind"], num_cols=["end_nav", "cagr", "max_dd", "vol"])
    compare_frames(c, nav_subset(mnv, ["strategy"], [20.8, 50.0]), nav_subset(env, ["strategy"], [20.8, 50.0]), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    # cost paid = sum of per-trade costs (extra reading, reported under its own check)
    c3 = Check("C-cost-paid"); C[c3.name] = c3
    compare_frames(c3, stat_subset(mst, ["strategy"], COSTS)[["book", "cost_bps", "kind", "cost_paid"]],
                   stat_subset(est, ["strategy"], COSTS)[["book", "cost_bps", "kind", "cost_paid"]],
                   ["book", "cost_bps", "kind"], num_cols=["cost_paid"], tol=1e-9)

    # C-comp: comparators
    c = Check("C-comp-hold-sleeve"); C[c.name] = c
    for kinds, chk in [(["hold_parent", "sleeve_only"], c)]:
        compare_frames(chk, stat_subset(mst, kinds, COSTS)[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                       stat_subset(est, kinds, COSTS)[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]],
                       ["book", "cost_bps", "kind"], num_cols=["end_nav", "cagr", "max_dd", "vol"])
        compare_frames(chk, nav_subset(mnv, kinds, COSTS), nav_subset(env, kinds, COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    for label, mixname in [("C-comp-mix", "constant_mix"), ("C-comp-mix-nofirst-rebalance", "constant_mix_nofirst")]:
        c = Check(label, gate=False); C[c.name] = c   # comparators are optional (spec rule 11); the initial position of the mix is not specified
        m1 = stat_subset(mst, [mixname], COSTS)[["book", "cost_bps", "end_nav", "cagr", "max_dd", "vol"]].assign(kind="constant_mix")
        e1 = stat_subset(est, ["constant_mix"], COSTS)[["book", "cost_bps", "kind", "end_nav", "cagr", "max_dd", "vol"]]
        compare_frames(c, m1, e1, ["book", "cost_bps", "kind"], num_cols=["end_nav", "cagr", "max_dd", "vol"])
        m2 = nav_subset(mnv, [mixname], COSTS).assign(run="constant_mix")
        compare_frames(c, m2, nav_subset(env, ["constant_mix"], COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])

    # ---- C-trades ----
    c = Check("C-trades"); C[c.name] = c
    mt = D["trades"].copy(); mt["cost_bps"] = r4(mt["cost_bps"])
    et = E["trades"].copy(); et["cost_bps"] = r4(et["cost_bps"])
    mt = mt[mt["run"] == "strategy"].copy(); et = et[et["run"] == "strategy"].copy()
    mt["seq"] = mt.groupby(["book", "cost_bps"]).cumcount(); et["seq"] = et.groupby(["book", "cost_bps"]).cumcount()
    et["date"] = et["date"].astype(str)
    compare_frames(c, mt, et, ["book", "cost_bps", "seq"], num_cols=["idx", "e_after", "V", "traded", "cost"], str_cols=["date", "kind", "basket_eff"])
    # number of trades per book x cost (stats 'trades' column and trade rows)
    cn = Check("C-trades-count"); C[cn.name] = cn
    cnt_m = mt.groupby(["book", "cost_bps"]).size().rename("n").reset_index()
    cnt_e = et.groupby(["book", "cost_bps"]).size().rename("n").reset_index()
    compare_frames(cn, cnt_m, cnt_e, ["book", "cost_bps"], num_cols=["n"], tol=0.0)
    compare_frames(cn, stat_subset(mst, ["strategy"], COSTS)[["book", "cost_bps", "kind", "trades"]],
                   stat_subset(est, ["strategy"], COSTS)[["book", "cost_bps", "kind", "trades"]], ["book", "cost_bps", "kind"], num_cols=["trades"], tol=0.0)

    # ---- C-null (sample of draws with NAV) ----
    c = Check("C-null"); C[c.name] = c
    ed = E["draws"]
    ed = ed[(ed["window"] == "full") & (ed["cash"] == "lbes") & (np.isclose(ed["cost_bps"], 20.8))]
    ed = ed[["book", "draw_type", "draw_id", "end_nav", "cagr", "max_dd"]]
    sd = D["sample_draws"]
    # restrict the evidence to the sampled keys; a sampled key absent from the evidence is "missing"
    ed_s = sd[["book", "draw_type", "draw_id"]].merge(ed, on=["book", "draw_type", "draw_id"], how="left")
    ed_s_ok = ed_s[ed_s["end_nav"].notna()]
    compare_frames(c, sd[sd.set_index(["book", "draw_type", "draw_id"]).index.isin(ed_s_ok.set_index(["book", "draw_type", "draw_id"]).index)],
                   ed_s_ok, ["book", "draw_type", "draw_id"], num_cols=["end_nav", "cagr", "max_dd"])
    n_absent = int(ed_s["end_nav"].isna().sum())
    if n_absent:
        c.missing += n_absent; c.fail("sampled draw absent from draws.csv")

    # ---- C-null-all (every N4.9 draw: invested weeks, spell counts, sorted spell lengths) ----
    c = Check("C-null-all"); C[c.name] = c
    ea = ed_all = E["draws"]
    ea = ea[(ea["draw_type"] == "N4.9") & (ea["window"] == "full")]
    ad = D["all_draws"]
    mm = ea.merge(ad, on=["book", "draw_id"], how="left", suffixes=("_e", "_v"))
    nomatch = mm["invested_weeks_v"].isna()
    c.missing += int(nomatch.sum())
    mm = mm[~nomatch]
    bad = ((mm["invested_weeks_e"] != mm["invested_weeks_v"]) | (mm["n_in_spells_e"] != mm["n_in_spells_v"]) |
           (mm["n_out_spells_e"] != mm["n_out_spells_v"]) | (~mm["sorted_same"].astype(bool)))
    c.compared += len(mm); c.failed += int(bad.sum())
    if bad.any():
        c.fail("first differing draw row: %s" % mm[bad].iloc[0][["book", "cost_bps", "draw_id", "invested_weeks_e", "invested_weeks_v", "n_in_spells_e", "n_in_spells_v", "n_out_spells_e", "n_out_spells_v", "sorted_same"]].to_dict())
    # coverage: every (book, window-full cost/cash combination) must hold exactly draw ids 0..1999
    for (b, cs, ca), g_ in ea.groupby(["book", "cost_bps", "cash"]):
        have = set(g_["draw_id"].tolist())
        lack = set(range(N_DRAWS)) - have
        if lack:
            c.missing += len(lack); c.fail(f"{b} cost {cs} cash {ca}: draw ids missing, e.g. {sorted(lack)[:3]}")
    if len(ea.groupby(["book", "cost_bps", "cash"])) < 16:
        c.missing += 1; c.fail("fewer than 16 (book, cost, cash) groups of N4.9 draws in draws.csv")
    # draws.csv must hold only ids inside 0..1999
    out = ea[~ea["draw_id"].between(0, N_DRAWS - 1)]
    c.compared += len(out); c.failed += len(out)
    # the engine's own example of draw states against the verifier's
    c = Check("C-draw-states"); C[c.name] = c
    if E["draw_states"] is None:
        c.missing += 1; c.fail("draw_states_example.csv absent")
    else:
        e_ = E["draw_states"].copy()
        compare_frames(c, D["draw_states"], e_[["book", "draw_id", "j", "decision_date", "real_state", "draw_state"]], ["book", "draw_id", "j"],
                       num_cols=["real_state", "draw_state"], str_cols=["decision_date"], tol=0.0)

    # ---- C-always-in (G0) ----
    c = Check("C-always-in"); C[c.name] = c
    ai = D["always_in"]
    c.compared = len(ai)
    badm = ai["gap_pp"].abs() > ai["limit_pp"]
    c.failed = int(badm.sum())
    if badm.any():
        c.fail("G0 exceeded: %s" % ai[badm].iloc[0].to_dict())

    # ---- C-audit (counts the engine wrote) ----
    c = Check("C-audit"); C[c.name] = c
    A = E["audit"]["books"]
    for p in BOOKS:
        if p not in A:
            c.missing += 1; c.fail(f"{p} absent from audit.json"); continue
        a = A[p]; m = D["meta"][p]
        pairs = [("t0", a["t0"], m["t0"]), ("sessions", a["sessions"], m["sessions"]), ("decisions", a["decisions"], m["decisions"]),
                 ("invested_weeks", a["invested_weeks"], m["invested_weeks"]), ("in_spells", a["in_spells"], m["in_spells"]),
                 ("out_spells", a["out_spells"], m["out_spells"]), ("round_trips", a["round_trips"], min(m["in_spells"], m["out_spells"])),
                 ("v2_decisions_checked", a["v2_decisions_checked"], m["decisions"]), ("v2_trades_checked", a["v2_trades_checked"], m["decisions"] - 1),
                 ("stale_label_weeks", a.get("stale_label_weeks(age>=5d, excluding T0)"), m["stale"]),
                 ("initial_basket_switch_session", a["initial_basket_switch_session"], m["initial_basket_switch_session"]),
                 ("skipped_baskets_dropped", a["skipped_baskets_dropped"], m["dropped"]),
                 ("cash.file_last", a["cash"]["file_last"], m["cash"]["file_last"]),
                 ("cash.accrued_sessions", a["cash"]["accrued_sessions"], m["cash"]["accrued_sessions"])]
        for nm, ae, mv in pairs:
            c.compared += 1
            if ae != mv:
                c.failed += 1; c.fail(f"{p} {nm}: verifier={mv!r} audit.json={ae!r}")
        c.compared += 1
        rr = abs(a["cash"]["daily_rate"] - m["cash"]["daily_rate"]) / abs(m["cash"]["daily_rate"])
        c.worst_rel = max(c.worst_rel, rr)
        if rr > TOL:
            c.failed += 1; c.fail(f"{p} cash daily_rate: verifier={m['cash']['daily_rate']!r} audit.json={a['cash']['daily_rate']!r}")
    return C


def summarise(C):
    gate_fail = sum(c.failed + c.missing for c in C.values() if c.gate)
    gate_compared = sum(c.compared for c in C.values() if c.gate)
    return gate_compared, gate_fail


def print_table(C, title):
    print(f"\n=== {title} ===")
    print(f"{'check':32s} {'compared':>10s} {'failed':>8s} {'missing':>8s} {'worst rel':>11s}  gate")
    for c in C.values():
        print(f"{c.name:32s} {c.compared:10d} {c.failed:8d} {c.missing:8d} {c.worst_rel:11.2e}  {'yes' if c.gate else 'info'}")
        if c.first_fail:
            print(f"    first problem: {c.first_fail}")


def corrupt_copy(evdir, dst):
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in ["decisions.csv", "daily_nav.csv", "stats.csv", "draws.csv", "trades.csv", "audit.json", "inputs.csv", "draw_states_example.csv"]:
        if (evdir / f).exists():
            shutil.copy(evdir / f, dst / f)
    dec = pd.read_csv(dst / "decisions.csv")
    rows = np.linspace(10, len(dec) - 10, 5).astype(int)
    dec.loc[rows, "state"] = 1 - dec.loc[rows, "state"]       # flip 5 decisions
    dec.to_csv(dst / "decisions.csv", index=False)
    nav = pd.read_csv(dst / "daily_nav.csv")
    m = (nav["run"] == "strategy") & (nav["cost_bps"] == 0.0)
    nav.loc[m, "nav"] = nav.loc[m, "nav"] * 1.001               # scale a NAV column by 1.001
    nav.to_csv(dst / "daily_nav.csv", index=False)
    return rows.tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T03" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    evdir = Path(args.evidence)
    out = Path(args.out) if args.out else evdir / "verify_t03.json"
    t = time.time()
    D = derive()
    print(f"[{time.time()-t:6.1f}s] derivation complete", flush=True)
    E = load_evidence(evdir)
    C = compare_all(D, E)
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)

    # always-in table
    ai = D["always_in"]
    print("\n=== C-always-in (0 cost, to 2026-10-22, model minus published, pp) ===")
    for p in BOOKS:
        a = ai[ai.book == p]
        ov = a[a.scope == "overall"].gap_pp.iloc[0]
        yy = a[a.scope != "overall"]
        w = yy.iloc[int(yy.gap_pp.abs().values.argmax())]
        print(f"{p}: CAGR gap {ov:+.4f} pp/yr (limit 0.25); worst calendar year {w.scope} {w.gap_pp:+.4f} pp (limit 0.5)")

    # worst relative differences for NAV and cost runs
    print("\n=== worst relative differences ===")
    for nm in ["C-nav0", "C-cost", "C-comp-hold-sleeve", "C-comp-mix", "C-comp-mix-nofirst-rebalance", "C-trades", "C-null"]:
        print(f"{nm:32s} {C[nm].worst_rel:.3e}")

    mix_lit, mix_alt = C["C-comp-mix"], C["C-comp-mix-nofirst-rebalance"]
    if mix_lit.failed or mix_alt.failed:
        print("\nFINDING (constant-mix comparator, not gating): literal reading of spec rule 11 (rebalance after EVERY decision, "
              "including the T0 decision) vs the engine: %d of %d rows differ, worst rel %.2e; reading without a rebalance after the T0 decision: "
              "%d of %d rows differ, worst rel %.2e. First differing row of the literal reading: %s"
              % (mix_lit.failed, mix_lit.compared, mix_lit.worst_rel, mix_alt.failed, mix_alt.compared, mix_alt.worst_rel, mix_lit.first_fail))

    selftest = None
    if not args.no_selftest:
        cdir = SCRATCH / "corrupt_evidence"
        rows = corrupt_copy(evdir, cdir)
        Ec = load_evidence(cdir)
        Cc = compare_all(D, Ec)
        print_table(Cc, f"SELF-TEST: corrupted copy in {cdir} (5 decision states flipped at rows {rows}, strategy cost-0 NAV x 1.001)")
        cc, cf = summarise(Cc)
        detected = cf > 0
        selftest = dict(dir=str(cdir), flipped_rows=rows, gate_compared=cc, gate_failures=cf, detected=bool(detected),
                        checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"corrupted copy detected: {detected} (failures {cf})")

    ok_real = gate_compared > 0 and gate_fail == 0
    ok = ok_real and (selftest is None or selftest["detected"])
    rep = dict(verifier="analysis/verify_t03.py", evidence=str(evdir), gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail),
               checks={k: v.to_dict() for k, v in C.items()}, always_in=ai.to_dict(orient="records"),
               meta={p: D["meta"][p] for p in BOOKS}, selftest=selftest, exit_ok=bool(ok),
               closed_form="NAV_end = prod over segments of (trade-day jump x fixed-unit segment growth); segment cumprod of daily growth reproduces the segment's NAV")
    out.write_text(json.dumps(rep, indent=1, default=str))
    print(f"\nrows compared (gate checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}")
    print(f"wrote {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
