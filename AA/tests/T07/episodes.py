"""T07 follow-up (post hoc, descriptive): where and why the whole-book switch beats the segment rule.

Reads only the evidence of the finished T07 run (evidence/headline/) and the engine's own price panel (approved data, through analysis/t07_engine.py).
Writes evidence/episodes/{stretches.csv, gap_curve.csv, summary.json}. Nothing here is pre-registered and nothing here changes the T07 verdict.

Definitions (the same as the results page's disagreement-weeks table):
  stretch   = a run of consecutive weekly decisions whose three signals are neither all BUY nor all SELL.
  window    = sessions from the first decision's trade session to the trade session of the decision after the last one (or the final session).
  gap       = log(rule NAV / whole-book NAV) at 20.8 bps (negative = the whole-book switch is ahead); over the windows it adds up exactly, and what is left is 'outside the stretches'.
  attribution (per window) = for every stock the rule keeps, its daily return minus the rule's own sleeve return, times its value the day before, summed
              and divided by the rule's NAV at the window start. 'Other' is the rest (costs, fills against closes, the whole-book switch's own sleeve).
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "analysis"))
import t07_engine as E  # noqa: E402

BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
COST = 20.8
EV = HERE / "evidence" / "headline"
OUT = HERE / "evidence" / "episodes"
BANDS = ["Large", "Mid", "Small and below"]


def stretches_of(dec: pd.DataFrame, cal: pd.DatetimeIndex):
    """(wk0, stretches) exactly as report.py builds them."""
    wk0 = [0]
    for t in dec.trade_date.iloc[1:]:
        if pd.isna(t):
            break
        wk0.append(int(np.searchsorted(cal.values, np.datetime64(pd.Timestamp(t)))))
    nw = len(wk0)
    wend = wk0[1:] + [len(cal) - 1]
    dis = dec["disagree"].astype(str).str.lower().eq("true").values[:nw]
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    nav = pd.read_csv(EV / "daily_nav.csv", parse_dates=["date"])
    dec_all = pd.read_csv(EV / "decisions.csv")
    es = pd.read_csv(EV / "event_stocks.csv", keep_default_na=False, na_values=[""])
    evt = pd.read_csv(EV / "events.csv", parse_dates=["trade_date"])
    pos_all = pd.read_csv(EV / "positions.csv", parse_dates=["date"])
    rows, curve_rows, summ = [], [], {"books": {}}
    for b in BOOKS:
        bk = E.Book(b)
        cal = bk.cal
        dec = dec_all[dec_all.book == b].reset_index(drop=True)
        n = lambda run: nav[(nav.book == b) & (nav.run == run) & (nav.cost_bps == COST)].set_index("date").nav.reindex(cal)
        seg, whole, parent = n("segment"), n("whole_book"), n("parent")
        assert seg.notna().all() and whole.notna().all()
        gap = np.log(seg.values / whole.values)
        for d_, g_, s_, w_ in zip(cal, gap, seg.values, whole.values):
            curve_rows.append({"book": b, "date": d_.date(), "gap_log": g_, "rule": s_, "whole": w_})
        wk0, sts, pat = stretches_of(dec, cal)
        # positions
        pos = pos_all[(pos_all.book == b) & (pos_all.run == "segment") & (pos_all.cost_bps == COST)]
        stock_cols = [f"{s}" for s in bk.stocks]
        cols = stock_cols + ["GOLDBEES", "LBES"]
        U = units_matrix(pos, cal, cols)
        Cs = bk.C  # closes of stocks (T x N)
        gcl, lcl = bk.g, bk.L
        px = np.column_stack([Cs, gcl, lcl])
        V = (U * px).sum(axis=1)
        first_pos = int(np.flatnonzero(V > 0)[0])  # the T0 position is not logged in positions.csv; the attribution starts at the first logged trade
        recon = np.nanmax(np.abs(V[first_pos:] / seg.values[first_pos:] - 1))
        # band of each stock at each session: tag of the latest event at or before the session
        ev_b = evt[(evt.book == b) & (evt.window == "full")].sort_values("event_no")
        es_b = es[(es.book == b) & (es.window == "full")]
        ev_dates = ev_b.trade_date.values
        ev_no = ev_b.event_no.values
        band_at = {}
        for no, g in es_b.groupby("event_no"):
            band_at[int(no)] = {s: bd for s, bd in zip(g.stock.values, g.band.values)}
        bidx = np.searchsorted(ev_dates, cal.values, side="right") - 1
        stock_index = {s: i for i, s in enumerate(stock_cols)}
        nst = len(stock_cols)
        # daily pnl by band relative to the rule's own sleeve (t uses units held at t-1)
        T = len(cal)
        exc = np.zeros((T, 3))
        unlabelled = 0   # held stock-days whose stock is missing from the tag list of the event that chose the position: must be 0
        sleeve_ret = np.zeros(T)
        kept_share = np.zeros(T)
        for t in range(1, T):
            ug, ul = U[t - 1, nst], U[t - 1, nst + 1]
            vg, vl = ug * gcl[t - 1], ul * lcl[t - 1]
            rs = ((ug * (gcl[t] - gcl[t - 1]) + ul * (lcl[t] - lcl[t - 1])) / (vg + vl)) if (vg + vl) > 0 else 0.0
            sleeve_ret[t] = rs
            vs = U[t - 1, :nst] * Cs[t - 1]
            kept_share[t] = vs.sum() / V[t - 1] if V[t - 1] > 0 else 0.0
            # the day's return is earned on the position held at t-1, which the latest event strictly before t chose: its tags apply (not an event on session t itself)
            mapd = band_at.get(int(ev_no[bidx[t - 1]]), {}) if bidx[t - 1] >= 0 else {}
            for i in np.flatnonzero(vs > 0):
                if Cs[t - 1, i] > 0:
                    r = Cs[t, i] / Cs[t - 1, i] - 1
                    bd = mapd.get(stock_cols[i])
                    if bd is None:
                        unlabelled += 1
                        continue
                    exc[t, BANDS.index(bd)] += vs[i] * (r - rs)
        covered = np.zeros(T, dtype=bool)
        tot_log = float(gap[-1] - gap[0])
        in_sum = 0.0
        for k, s in enumerate(sts):
            a, e = s["s"], s["e"]
            rr = seg.values[e] / seg.values[a] - 1
            ww = whole.values[e] / whole.values[a] - 1
            lg = float(gap[e] - gap[a])
            in_sum += lg
            covered[a + 1:e + 1] = True
            ok = a >= first_pos
            by_band = (exc[a + 1:e + 1].sum(axis=0)) / V[a] if ok else np.full(3, np.nan)
            rows.append({"book": b, "stretch": k + 1, "from": s["from"], "to": s["to"], "weeks": s["weeks"], "patterns": "→".join(s["patterns"]),
                         "before": s["before"], "after": s["after"], "kind": kind_of(s["before"], s["after"]),
                         "start": str(cal[a].date()), "end": str(cal[e].date()), "sessions": int(e - a),
                         "rule_ret": rr, "whole_ret": ww, "rule_minus_whole": rr - ww, "gap_log_rule_over_whole": lg,
                         "attribution_ok": bool(ok), "kept_share_mean": float(kept_share[a + 1:e + 1].mean()) if ok else np.nan,
                         "sleeve_ret": float(np.prod(1 + sleeve_ret[a + 1:e + 1]) - 1) if ok else np.nan,
                         "excess_large_pp": 100 * by_band[0], "excess_mid_pp": 100 * by_band[1], "excess_small_pp": 100 * by_band[2],
                         "excess_total_pp": 100 * by_band.sum(), "rule_minus_whole_pp": 100 * (rr - ww),
                         "other_pp": 100 * ((rr - ww) - by_band.sum())})
        summ["books"][b] = {"sessions": int(T), "start": str(cal[0].date()), "end": str(cal[-1].date()), "first_logged_position": str(cal[first_pos].date()), "stockdays_without_band": int(unlabelled), "recon_max_rel_err": float(recon),
                            "total_gap_log": tot_log, "in_stretches_log": in_sum, "outside_log": tot_log - in_sum,
                            "years": float((cal[-1] - cal[0]).days / 365.25), "cagr_rule": float((seg.values[-1] / seg.values[0]) ** (365.25 / (cal[-1] - cal[0]).days) - 1),
                            "cagr_whole": float((whole.values[-1] / whole.values[0]) ** (365.25 / (cal[-1] - cal[0]).days) - 1),
                            "n_stretches": len(sts), "stretches_whole_ahead": int(sum(1 for r in rows if r["book"] == b and r["rule_minus_whole"] < 0))}
    df = pd.DataFrame(rows)
    cv = pd.DataFrame(curve_rows)
    df.to_csv(OUT / "stretches.csv", index=False)
    cv.to_csv(OUT / "gap_curve.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    from episodes_page import build_fragment
    (OUT / "fragment.html").write_text(build_fragment(df, cv, summ), encoding="utf-8")
    print(json.dumps({b: {k: round(v, 4) if isinstance(v, float) else v for k, v in x.items()} for b, x in summ["books"].items()}, indent=1))


if __name__ == "__main__":
    main()
