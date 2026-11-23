"""T12 follow-up (post hoc, descriptive): where and why the whole-book switch and the segment rule part ways, stretch by stretch.

    python tests/T12/episodes.py [--run headline]                 reads evidence/<run>/, writes evidence/episodes/
    python tests/T12/episodes.py --evidence DIR [--out DIR]       another evidence directory (default output DIR/episodes)

Fork of tests/T07/episodes.py with one change of method: T07's version imported the engine for its price panel; this one imports nothing from the
engine (analysis/t12_engine.py) and reads the prices itself from the APPROVED rows of data/APPROVED_DATA.md (its own parse): D18 closes with
price_corrections.csv applied, GOLDBEES closes (D09), the LBES level (D11), each carried forward over the run's own calendar (the sessions of
daily_nav.csv), which is how the evidence contract's stand-ins work (2017-10-19 no D18 bar, 2016-10-30 no GOLDBEES bar: the previous close).
It writes evidence/episodes/{stretches.csv, gap_curve.csv, summary.json}; report.py draws them (section 'whywhole', hoverable).
Nothing here is pre-registered and nothing here changes the T12 verdict.

Definitions (the same as the results page's disagreement-weeks table):
  stretch   = a run of consecutive weekly decisions whose three signals are neither all BUY nor all SELL.
  window    = sessions from the first decision's trade session to the trade session of the decision after the last one (or the final session).
  gap       = log(rule NAV / whole-book NAV) at 20.8 bps (negative = the whole-book switch is ahead); over the windows it adds up exactly, and what is left is 'outside the stretches'.
  attribution (per window) = for every stock the rule keeps, its daily return minus the rule's own sleeve return, times its value the day before, summed
              and divided by the rule's NAV at the window start. 'Other' is the rest (costs, fills against closes, the whole-book switch's own sleeve).
  recon     = the largest relative gap between sum(units x close) from positions.csv and the rule's NAV in daily_nav.csv after the first logged position:
              it shows whether the attribution rests on the engine's own holdings and prices.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
COST = 20.8
BANDS = ["Large", "Mid", "Small and below"]


def approved_files() -> dict:
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    out = {}
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            if c[0] == "APPROVED":
                out[c[2].replace("\\", "/")] = c[1]
    return out


def need(appr: dict, rel: str) -> Path:
    if rel not in appr:
        raise SystemExit(f"{rel} is not an APPROVED row of data/APPROVED_DATA.md: refusing to read it")
    return AA / rel


def stretches_of(dec: pd.DataFrame, cal: pd.DatetimeIndex):
    """(wk0, stretches, patterns) exactly as report.py builds them."""
    wk0 = [0]
    for t in dec.trade_date.iloc[1:]:
        if pd.isna(t) or str(t) == "":
            break
        wk0.append(int(np.searchsorted(cal.values, np.datetime64(pd.Timestamp(t)))))
    nw = len(wk0)
    wend = wk0[1:] + [len(cal) - 1]
    dis = dec["disagree"].astype(str).str.lower().isin(["true", "1", "1.0"]).values[:nw]
    pat = ["".join("B" if dec.loc[j, f"sign_{s}"] == "BUY" else "S" for s in ("Nifty100", "MC100", "SC100")) for j in range(nw)]
    out, j = [], 0
    while j < nw:
        if dis[j]:
            j2 = j
            while j2 + 1 < nw and dis[j2 + 1]:
                j2 += 1
            before = pat[j - 1] if j > 0 else None
            after = pat[j2 + 1] if j2 + 1 < nw else None
            out.append({"j": j, "k": j2, "s": wk0[j], "e": wend[j2], "from": str(dec.decision_date.iloc[j]), "to": str(dec.decision_date.iloc[j2]),
                        "weeks": j2 - j + 1, "patterns": list(dict.fromkeys(pat[j:j2 + 1])), "before": before, "after": after})
            j = j2 + 1
        else:
            j += 1
    return wk0, out, pat


def kind_of(before, after):
    """Where the stretch sits between the all-SELL (SSS) and all-BUY (BBB) states."""
    if before == "SSS" and after == "BBB":
        return "Recovery: SELL, then partial, then all BUY"
    if before == "SSS" and after == "SSS":
        return "False start: SELL, partial, back to SELL"
    if before == "BBB" and after == "SSS":
        return "Decline: BUY, then partial, then all SELL"
    if before == "BBB" and after == "BBB":
        return "Shake-out: BUY, partial, back to BUY"
    return "Open at the window's edge"


def units_matrix(pos: pd.DataFrame, cal: pd.DatetimeIndex, cols: list):
    """Units held after each session's trades, forward-filled; a session with a trade lists every non-zero holding."""
    T = len(cal)
    U = np.zeros((T, len(cols)))
    idx = {c: i for i, c in enumerate(cols)}
    cur = np.zeros(len(cols))
    byd = {d: g for d, g in pos.groupby("date")}
    for t, d in enumerate(cal):
        if d in byd:
            cur = np.zeros(len(cols))
            g = byd[d]
            for ins, u in zip(g.instrument.values, g.units.values):
                cur[idx[ins]] = u
        U[t] = cur
    return U


def prices(appr, b, stocks, cal, cash_cache={}):
    """(T x N) stock closes (D18, Polyplex correction), GOLDBEES close and LBES level, each carried forward over `cal`."""
    oh = pd.read_csv(need(appr, f"data/holdings_matrix/{b}_ohlc.csv"), usecols=["date", "stock", "close"], parse_dates=["date"])
    oh = oh[oh.stock.isin(stocks) & (oh.date <= cal[-1])]
    pc = pd.read_csv(need(appr, "data/holdings_matrix/price_corrections.csv"))
    for r in pc.itertuples():
        if str(r.applies_to) == b:
            m = (oh.stock == r.stock) & (oh.date < pd.Timestamp(r.ex_date))
            oh.loc[m, "close"] = oh.loc[m, "close"] * float(r.factor)
    C = oh.pivot_table(index="date", columns="stock", values="close").reindex(columns=stocks)
    C = C.reindex(C.index.union(cal)).ffill().reindex(cal).values
    if "g" not in cash_cache:
        gp = [f for f in appr if f.startswith("analysis/cache/why_gold_ohlc_eikon_extended_") and f.endswith(".parquet")]
        g = pd.read_parquet(AA / sorted(gp)[-1])
        g["date"] = pd.to_datetime(g["date"])
        gs = g.set_index("date").close.sort_index()
        lp = [f for f in appr if re.match(r"Historical Data/LBES_Adjusted_Price_data_extended_.*\.csv$", f)]
        lb = pd.read_csv(AA / sorted(lp)[-1])
        lb["d"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
        ls = lb.set_index("d").price.sort_index()
        ls = ls[~ls.index.duplicated(keep="last")]
        cash_cache["g"], cash_cache["l"] = gs, ls
    gs, ls = cash_cache["g"], cash_cache["l"]
    gcl = gs.reindex(gs.index.union(cal)).ffill().reindex(cal).values
    lcl = ls.reindex(ls.index.union(cal)).ffill().reindex(cal).values
    return C, gcl, lcl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="output directory (default evidence/episodes for --run, DIR/episodes for --evidence)")
    ap.add_argument("--books", default=None)
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    EV = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    OUT = Path(a.out) if a.out else ((EV / "episodes") if a.evidence else HERE / "evidence" / "episodes")
    OUT.mkdir(parents=True, exist_ok=True)
    appr = approved_files()
    nav = pd.read_csv(EV / "daily_nav.csv", parse_dates=["date"])
    dec_all = pd.read_csv(EV / "decisions.csv", keep_default_na=False, na_values=[""])
    es = pd.read_csv(EV / "event_stocks.csv", keep_default_na=False, na_values=[""])
    evt = pd.read_csv(EV / "events.csv", parse_dates=["trade_date"])
    pos_all = pd.read_csv(EV / "positions.csv", parse_dates=["date"])
    rows, curve_rows, summ = [], [], {"run": EV.name, "books": {}}
    for b in BOOKS:
        cal = pd.DatetimeIndex(nav[(nav.book == b) & (nav.run == "segment") & (nav.cost_bps == COST)].sort_values("date").date.values)
        dec = dec_all[dec_all.book == b].sort_values("j").reset_index(drop=True)
        n = lambda run: nav[(nav.book == b) & (nav.run == run) & (nav.cost_bps == COST)].set_index("date").nav.reindex(cal)
        seg, whole = n("segment"), n("whole_book")
        assert seg.notna().all() and whole.notna().all(), f"{b}: daily_nav.csv lacks segment or whole_book rows at 20.8 bps"
        gap = np.log(seg.values / whole.values)
        for d_, g_, s_, w_ in zip(cal, gap, seg.values, whole.values):
            curve_rows.append({"book": b, "date": d_.date(), "gap_log": g_, "rule": s_, "whole": w_})
        wk0, sts, pat = stretches_of(dec, cal)
        pos = pos_all[(pos_all.book == b) & (pos_all.run == "segment") & (pos_all.cost_bps == COST)]
        ins = sorted(set(pos.instrument))
        held_stocks = sorted(set(es[(es.book == b) & (es.window == "full")].stock))
        gold_ins = [x for x in ins if x not in held_stocks and "GOLD" in x.upper()]
        cash_ins = [x for x in ins if x not in held_stocks and x not in gold_ins and any(k_ in x.upper() for k_ in ("LBES", "CASH", "LIQ"))]
        unknown = [x for x in ins if x not in held_stocks and x not in gold_ins + cash_ins]
        stock_cols = held_stocks
        cols = stock_cols + gold_ins + cash_ins
        U = units_matrix(pos, cal, cols)
        Cs, gcl, lcl = prices(appr, b, stock_cols, cal)
        nst = len(stock_cols)
        px = np.column_stack([Cs] + [gcl] * len(gold_ins) + [lcl] * len(cash_ins))
        V = np.nansum(U * px, axis=1)
        logged = np.flatnonzero(V > 0)
        first_pos = int(logged[0]) if len(logged) else len(cal)
        recon = float(np.nanmax(np.abs(V[first_pos:] / seg.values[first_pos:] - 1))) if len(logged) else float("nan")
        ev_b = evt[(evt.book == b) & (evt.window == "full")].sort_values("event_no")
        es_b = es[(es.book == b) & (es.window == "full")]
        ev_dates = ev_b.trade_date.values
        ev_no = ev_b.event_no.values
        band_at = {int(no): dict(zip(g.stock.values, g.band.values)) for no, g in es_b.groupby("event_no")}
        bidx = np.searchsorted(ev_dates, cal.values, side="right") - 1
        T = len(cal)
        exc = np.zeros((T, 3))
        unlabelled = 0
        sleeve_ret = np.zeros(T)
        kept_share = np.zeros(T)
        gi = list(range(nst, nst + len(gold_ins) + len(cash_ins)))
        for t in range(1, T):
            vprev = U[t - 1, gi] * px[t - 1, gi]
            vs_ = vprev.sum()
            rs = float((U[t - 1, gi] * (px[t, gi] - px[t - 1, gi])).sum() / vs_) if vs_ > 0 else 0.0
            sleeve_ret[t] = rs
            vs = U[t - 1, :nst] * Cs[t - 1]
            kept_share[t] = np.nansum(vs) / V[t - 1] if V[t - 1] > 0 else 0.0
            mapd = band_at.get(int(ev_no[bidx[t - 1]]), {}) if bidx[t - 1] >= 0 else {}
            for i in np.flatnonzero(np.nan_to_num(vs) > 0):
                if Cs[t - 1, i] > 0:
                    r = Cs[t, i] / Cs[t - 1, i] - 1
                    bd = mapd.get(stock_cols[i])
                    if bd is None:
                        unlabelled += 1
                        continue
                    exc[t, BANDS.index(bd)] += vs[i] * (r - rs)
        tot_log = float(gap[-1] - gap[0])
        in_sum = 0.0
        for k, s in enumerate(sts):
            a_, e_ = s["s"], s["e"]
            rr = seg.values[e_] / seg.values[a_] - 1
            ww = whole.values[e_] / whole.values[a_] - 1
            lg = float(gap[e_] - gap[a_])
            in_sum += lg
            ok = a_ >= first_pos
            by_band = (exc[a_ + 1:e_ + 1].sum(axis=0)) / V[a_] if ok and V[a_] > 0 else np.full(3, np.nan)
            rows.append({"book": b, "stretch": k + 1, "from": s["from"], "to": s["to"], "weeks": s["weeks"], "patterns": "→".join(s["patterns"]),
                         "before": s["before"], "after": s["after"], "kind": kind_of(s["before"], s["after"]),
                         "start": str(cal[a_].date()), "end": str(cal[e_].date()), "sessions": int(e_ - a_),
                         "rule_ret": rr, "whole_ret": ww, "rule_minus_whole": rr - ww, "gap_log_rule_over_whole": lg,
                         "attribution_ok": bool(ok), "kept_share_mean": float(kept_share[a_ + 1:e_ + 1].mean()) if ok else np.nan,
                         "sleeve_ret": float(np.prod(1 + sleeve_ret[a_ + 1:e_ + 1]) - 1) if ok else np.nan,
                         "excess_large_pp": 100 * by_band[0], "excess_mid_pp": 100 * by_band[1], "excess_small_pp": 100 * by_band[2],
                         "excess_total_pp": 100 * np.nansum(by_band), "rule_minus_whole_pp": 100 * (rr - ww),
                         "other_pp": 100 * ((rr - ww) - np.nansum(by_band))})
        summ["books"][b] = {"sessions": int(T), "start": str(cal[0].date()), "end": str(cal[-1].date()),
                            "first_logged_position": str(cal[first_pos].date()) if first_pos < T else None, "stockdays_without_band": int(unlabelled), "recon_max_rel_err": recon,
                            "instruments_not_priced": unknown, "total_gap_log": tot_log, "in_stretches_log": in_sum, "outside_log": tot_log - in_sum,
                            "n_stretches": len(sts), "stretches_whole_ahead": int(sum(1 for r in rows if r["book"] == b and r["rule_minus_whole"] < 0))}
    df = pd.DataFrame(rows)
    cv = pd.DataFrame(curve_rows)
    df.to_csv(OUT / "stretches.csv", index=False)
    cv.to_csv(OUT / "gap_curve.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print("wrote", OUT)
    print(json.dumps({b: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in x.items()} for b, x in summ["books"].items()}, indent=1))


if __name__ == "__main__":
    main()
