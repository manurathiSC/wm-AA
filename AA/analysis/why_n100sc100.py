# -*- coding: utf-8 -*-
"""
Why does "N100 AND SC100" look so much better than Smallcap 100 alone and the
current rule? A forensic study, in six parts:

  A. Attribution, in-sample (2021-11 -> 2026-08, the four books). Two rules
     earn different returns only on the weeks they disagree, so the gap is
     exactly the sum over those weeks of (equity return - sleeve return), with
     the sign of whichever rule held equity. That locates the edge in time.
  B. Switch anatomy. At every entry and exit, which index moved first, how
     far ahead of the single-index rules it was, and what equity and gold
     did next.
  C. Signal states. For each weekly state (both BUY / only N100 / only SC100 /
     both SELL): the forward returns of large caps, small caps, the parents
     and gold. This is the mechanism test.
  D. Out of sample on the indices, 2007-07 -> 2021-10, before the AA books
     existed and before Study 1 chose the rule. The main test uses an all-cash
     sleeve (no gold history before 2014-07); there is also a 50/50 test from
     2014-07.
  E. Out of sample on the actual parents, 2014-07 -> 2021-10. Their real
     baskets, priced from ohlcv_eikon, run through the v2 harness. Includes a
     current-rule proxy: FS >= 0.60 on rank-band tags, with Midcap 100 /
     Smallcap 100 standing in for Midcap 150 / Smallcap 250, which have no
     signals before 2019.
  F. Robustness: circular signal shifts, a one-week delay, leave-one-episode
     out, and other large-plus-small pairs.

Writes everything to `evidence/why_n100sc100/`.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
from common import CACHE_DIR, DATA_DIR, EVIDENCE_DIR, PAIRS

OUT = EVIDENCE_DIR / "why_n100sc100"
OUT.mkdir(parents=True, exist_ok=True)
SEG = EVIDENCE_DIR / "segment_v2"
COST = 20.8
SIGS = ["Nifty100", "SC100", "NSEI", "MC100", "NiftySmallcap250", "NiftyMidcap150", "NiftyMicrocap250"]
SHORT = {"Nifty100": "N100", "SC100": "SC100", "NSEI": "N50", "MC100": "MC100",
         "NiftySmallcap250": "SC250", "NiftyMidcap150": "MC150", "NiftyMicrocap250": "Micro250"}
IDX_SHEETS = {"N100": "Nifty100", "SC100": "SC100", "N50": "NSEI", "MC100": "MC100",
              "SC250": "NiftySmallcap250", "MC150": "NiftyMidcap150"}
IS_START, IS_END = pd.Timestamp("2021-11-03"), pd.Timestamp("2026-08-21")
OOS_START, OOS_END = pd.Timestamp("2007-07-02"), pd.Timestamp("2021-10-29")
OOS_GOLD_START = pd.Timestamp("2014-07-07")


# ── Data ───────────────────────────────────────────────────────────────────
def calendar() -> pd.DatetimeIndex:
    d = pd.read_csv(D.CALENDAR_CSV)
    return pd.DatetimeIndex(pd.to_datetime(d["date"]).unique()).sort_values()


def weekly_signs() -> pd.DataFrame:
    """Production SIGN per index on the union of Friday dates, as 1 (BUY) / 0 (SELL)."""
    cols = {}
    for n in SIGS:
        d = pd.read_excel(D.MASTER_DIR / f"Master_{n}.xlsx")
        d["Date"] = pd.to_datetime(d["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        cols[SHORT[n]] = s[~s.index.duplicated(keep="last")].map({"BUY": 1.0, "SELL": 0.0})
    w = pd.DataFrame(cols).sort_index()
    # A few indices publish on a slightly different Friday; carry one week at most.
    return w.ffill(limit=1)


def index_closes(cal) -> pd.DataFrame:
    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    out = {}
    for k, sh in IDX_SHEETS.items():
        d = pd.read_excel(xl, sheet_name=sh)
        d["date"] = pd.to_datetime(d["date"])
        s = d.set_index("date")["close"].astype(float).sort_index()
        out[k] = s[~s.index.duplicated()]
    return pd.DataFrame(out).reindex(cal).ffill(limit=5)


def eikon_by_isin(isins, start, end, cache: str) -> pd.DataFrame:
    path = CACHE_DIR / cache
    if path.exists():
        return pd.read_parquet(path)
    qm = D._read_sql("SELECT DISTINCT quote_id, isin, new_isin FROM symbology_changes "
                     "WHERE isin = ANY(:i) OR new_isin = ANY(:i)", {"i": list(isins)})
    pairs = {(i, int(r["quote_id"])) for _, r in qm.iterrows()
             for i in {r["isin"], r["new_isin"]} & set(isins)}
    qm = pd.DataFrame(sorted(pairs), columns=["isin", "quote_id"])
    q = [int(x) for x in qm["quote_id"].unique()]
    frames = []
    for i in range(0, len(q), 150):
        frames.append(D._read_sql(
            "SELECT quote_id, ric, date, open, high, low, close FROM ohlcv_eikon "
            "WHERE quote_id = ANY(:q) AND date >= :s AND date <= :e",
            {"q": q[i:i + 150], "s": str(start.date()), "e": str(end.date())}))
    ek = pd.concat(frames, ignore_index=True)
    ek["date"] = pd.to_datetime(ek["date"])
    for c in ("open", "high", "low", "close"):
        ek[c] = pd.to_numeric(ek[c], errors="coerce").astype(float)
    ek = ek.merge(qm, on="quote_id").sort_values(["isin", "date", "quote_id"]) \
        .drop_duplicates(["isin", "date"])
    px = ek.rename(columns={"isin": "ticker"})[["date", "ticker", "open", "high", "low", "close", "ric"]]
    px.to_parquet(path, index=False)
    return px


def gold_cash(cal) -> pd.DataFrame:
    """GOLDBEES close (Eikon GBES.NS, from 2014-07) and the LBES total-return level."""
    path = CACHE_DIR / "why_gold_eikon.parquet"
    if path.exists():
        g = pd.read_parquet(path)
    else:
        g = D._read_sql("SELECT date, close FROM ohlcv_eikon WHERE quote_id = 55837402194 ORDER BY date")
        g["date"] = pd.to_datetime(g["date"])
        g["close"] = g["close"].astype(float)
        g.to_parquet(path, index=False)
    gold = g.set_index("date")["close"].reindex(cal).ffill(limit=5)
    lb = pd.read_csv(DATA_DIR / "LBES_Adjusted_Price_data_2026_08_10.csv")
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    cash = lb.set_index("date")["price"].astype(float).sort_index()
    cash = cash[~cash.index.duplicated()].reindex(cal.union(cash.index)).ffill().reindex(cal)
    return pd.DataFrame({"gold": gold, "cash": cash})


# ── Return-space simulator for index-level tests ───────────────────────────
def daily_weight(decisions: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    """
    Weekly decisions (1 = equity) -> the equity weight earning each session's
    return. A decision dated Friday R is traded at the close of the next
    session, so it first earns the return of the session after that.
    """
    w = pd.Series(np.nan, index=cal)
    for r, v in decisions.dropna().items():
        j = cal.searchsorted(r, side="right")          # entry session
        if j + 1 < len(cal):
            w.iloc[j + 1] = v
    return w.ffill()


def run_rs(dec: pd.Series, r_eq: pd.Series, r_sl: pd.Series, cal, cost_bps=COST) -> pd.Series:
    """NAV of: e * equity + (1 - e) * sleeve, rebalanced daily, cost on each switch."""
    w = daily_weight(dec, cal).reindex(r_eq.index).ffill().fillna(1.0)
    r = w * r_eq + (1 - w) * r_sl
    sw = w.diff().abs().fillna(0.0)
    r = r - sw * cost_bps / 1e4
    return (1 + r.fillna(0.0)).cumprod()


def cagr(nav: pd.Series) -> float:
    n = nav.dropna()
    yrs = (n.index[-1] - n.index[0]).days / 365.25
    return float((n.iloc[-1] / n.iloc[0]) ** (1 / yrs) - 1)


def mdd(nav: pd.Series) -> float:
    n = nav.dropna()
    return float((n / n.cummax() - 1).min())


def vol(nav: pd.Series) -> float:
    return float(nav.pct_change().std() * np.sqrt(252))


RULES = {
    "buy_hold": lambda s: pd.Series(1.0, index=s.index),
    "SC100 only": lambda s: s["SC100"],
    "N100 only": lambda s: s["N100"],
    "N100 AND SC100": lambda s: s["N100"] * s["SC100"],
    "N100 OR SC100": lambda s: ((s["N100"] + s["SC100"]) > 0).astype(float),
    "N50 AND SC100": lambda s: s["N50"] * s["SC100"],
    "N100 AND MC100": lambda s: s["N100"] * s["MC100"],
    "MC100 AND SC100": lambda s: s["MC100"] * s["SC100"],
    "N100 AND MC100 AND SC100": lambda s: s["N100"] * s["MC100"] * s["SC100"],
}


def main() -> None:
    t0 = time.time()
    cal = calendar()
    sg = weekly_signs()
    idx = index_closes(cal)
    gc = gold_cash(cal)
    res = {}

    # ── C. signal states: forward returns, in-sample and out of sample ─────
    def state_table(s, start, end, assets: dict) -> pd.DataFrame:
        s = s.loc[(s.index >= start) & (s.index <= end), ["N100", "SC100"]].dropna()
        rows = []
        for r, v in s.iterrows():
            j = cal.searchsorted(r, side="right")
            if j + 5 >= len(cal):
                continue
            a, b = cal[j], cal[min(j + 5, len(cal) - 1)]          # ~1 week forward
            c = cal[min(j + 21, len(cal) - 1)]                      # ~1 month forward
            row = {"review": r, "state": ("both BUY" if v.N100 and v.SC100 else
                                          "only N100 BUY" if v.N100 else
                                          "only SC100 BUY" if v.SC100 else "both SELL")}
            for k, lv in assets.items():
                if a in lv.index and pd.notna(lv.get(a)) and pd.notna(lv.get(b)):
                    row[f"{k}_1w"] = lv[b] / lv[a] - 1
                if a in lv.index and pd.notna(lv.get(a)) and pd.notna(lv.get(c)):
                    row[f"{k}_4w"] = lv[c] / lv[a] - 1
            rows.append(row)
        return pd.DataFrame(rows)

    nav = pd.read_csv(SEG / "nav_curves.csv", index_col=0, parse_dates=True)
    par = nav[[f"{a}|parent|0" for a in PAIRS]].mean(axis=1)        # avg of the 4 harness parents
    assets_is = {"SC100": idx["SC100"], "N100": idx["N100"], "parents": par, "gold": gc["gold"]}
    st_is = state_table(sg, IS_START, IS_END, assets_is)
    st_oos = state_table(sg, OOS_START, OOS_END, {"SC100": idx["SC100"], "N100": idx["N100"],
                                                   "MC100": idx["MC100"], "gold": gc["gold"]})
    st_is.to_csv(OUT / "states_in_sample.csv", index=False)
    st_oos.to_csv(OUT / "states_oos.csv", index=False)

    def summ(st):
        g = st.groupby("state")
        o = g.size().rename("weeks").to_frame()
        for c in [c for c in st.columns if c.endswith(("_1w", "_4w"))]:
            o[c + "_mean"] = g[c].mean()
            o[c + "_hit"] = g[c].apply(lambda x: (x.dropna() > 0).mean() if x.notna().any() else np.nan)
            o[c + "_n"] = g[c].count()
        return o
    s_is, s_oos = summ(st_is), summ(st_oos)
    s_is.to_csv(OUT / "states_in_sample_summary.csv")
    s_oos.to_csv(OUT / "states_oos_summary.csv")
    res["states"] = {"in_sample": s_is.reset_index().to_dict(orient="records"),
                     "oos": s_oos.reset_index().to_dict(orient="records")}
    print(f"C done ({time.time() - t0:.0f}s)")

    # ── D. out of sample on the indices ────────────────────────────────────
    def oos_block(start, end, sleeve: str):
        c = cal[(cal >= start) & (cal <= end)]
        if sleeve == "cash":
            r_sl = gc["cash"].reindex(c).pct_change()
        else:
            r_sl = 0.5 * gc["gold"].reindex(c).pct_change() + 0.5 * gc["cash"].reindex(c).pct_change()
        s = sg.loc[(sg.index >= start - pd.Timedelta(days=7)) & (sg.index <= end)]
        eqs = {"SC100": idx["SC100"], "N100": idx["N100"], "MC100": idx["MC100"],
               "blend N100/MC100/SC100": None}
        rets = {k: v.reindex(c).pct_change() for k, v in eqs.items() if v is not None}
        rets["blend N100/MC100/SC100"] = (rets["SC100"] + rets["N100"] + rets["MC100"]) / 3
        rows, curves = [], {}
        for ek, r_eq in rets.items():
            for rn, f in RULES.items():
                dec = f(s).dropna()
                navs = run_rs(dec, r_eq.fillna(0.0), r_sl.fillna(0.0), c)
                d = daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
                rows.append({"equity": ek, "rule": rn, "sleeve": sleeve, "start": c[0].date(),
                             "end": c[-1].date(), "cagr": cagr(navs), "max_dd": mdd(navs),
                             "vol": vol(navs), "time_in_equity": float(d.mean()),
                             "switches": int((dec.diff().abs() > 0).sum())})
                if ek in ("SC100", "blend N100/MC100/SC100"):
                    curves[f"{ek}|{rn}"] = navs
        return pd.DataFrame(rows), pd.DataFrame(curves)

    d1, c1 = oos_block(OOS_START, OOS_END, "cash")
    d2, c2 = oos_block(OOS_GOLD_START, OOS_END, "gold+cash")
    di, ci = oos_block(IS_START, IS_END, "gold+cash")
    dcash_is, _ = oos_block(IS_START, IS_END, "cash")
    pd.concat([d1, d2, di.assign(sleeve="gold+cash (in-sample)"),
               dcash_is.assign(sleeve="cash (in-sample)")]).to_csv(OUT / "index_backtests.csv", index=False)
    c1.to_csv(OUT / "index_curves_oos_cash.csv")
    c2.to_csv(OUT / "index_curves_oos_gold.csv")
    ci.to_csv(OUT / "index_curves_in_sample.csv")

    # Year by year, out of sample, on the blend: where does the AND rule win?
    blend = (idx["SC100"].pct_change() + idx["N100"].pct_change() + idx["MC100"].pct_change()) / 3
    yrows = []
    for key in ["buy_hold", "SC100 only", "N100 AND SC100", "N100 only"]:
        n = c1[f"blend N100/MC100/SC100|{key}"]
        ye = n.groupby(n.index.year).last()
        yr = ye / pd.concat([pd.Series([n.iloc[0]], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:] - 1
        for y, v in yr.items():
            yrows.append({"rule": key, "year": int(y), "return": float(v)})
    pd.DataFrame(yrows).to_csv(OUT / "oos_yearly_blend_cash.csv", index=False)
    print(f"D done ({time.time() - t0:.0f}s)")

    # ── B. switch anatomy (whole history, from the signals) ────────────────
    s = sg[["N100", "SC100"]].dropna()
    s = s[s.index >= pd.Timestamp("2006-01-06")]
    both = s["N100"] * s["SC100"]
    rows = []
    for i in range(1, len(s)):
        r, prev, cur = s.index[i], both.iloc[i - 1], both.iloc[i]
        if prev == cur:
            continue
        if cur == 0:                                           # exit
            who = [SHORT_K for SHORT_K, v in (("N100", s["N100"].iloc[i]), ("SC100", s["SC100"].iloc[i])) if v == 0]
            # When does SC100-only exit? The first week at or after r with SC100 == 0.
            sc_exit = s.index[(s.index >= r) & (s["SC100"] == 0)]
            lead = int(((s.index > r) & (s.index <= sc_exit[0])).sum()) if len(sc_exit) else None
            kind = "exit"
        else:                                                  # entry
            who = ["N100" if s["N100"].iloc[i - 1] == 0 else "SC100"]
            sc_entry = s.index[(s.index <= r) & (s["SC100"] == 1)]
            # weeks SC100-only was already in before the AND rule entered
            last_sc0 = s.index[(s.index < r) & (s["SC100"] == 0)]
            lead = int(((s.index > last_sc0[-1]) & (s.index < r)).sum()) if len(last_sc0) else None
            kind = "entry"
        j = cal.searchsorted(r, side="right")
        fwd = {}
        for k in ("SC100", "N100"):
            lv = idx[k]
            a = cal[j] if j < len(cal) else None
            for h, lab in ((21, "1m"), (63, "3m")):
                b = cal[min(j + h, len(cal) - 1)] if j < len(cal) else None
                fwd[f"{k}_{lab}"] = float(lv[b] / lv[a] - 1) if a is not None and pd.notna(lv.get(a)) and pd.notna(lv.get(b)) else None
        rows.append({"review": r.date(), "kind": kind, "triggered_by": "+".join(who),
                     "weeks_vs_sc100_only": lead, **fwd})
    an = pd.DataFrame(rows)
    an.to_csv(OUT / "switch_anatomy.csv", index=False)
    print(f"B done ({time.time() - t0:.0f}s)")

    # ── A. attribution, in-sample, on the four books ───────────────────────
    exp = pd.read_csv(SEG / "exposure_daily.csv", index_col=0, parse_dates=True)
    sl = pd.read_csv(SEG / "nav_curves.csv", index_col=0, parse_dates=True)
    c = exp.index
    r_sl = (0.5 * gc["gold"].reindex(c).pct_change() + 0.5 * gc["cash"].reindex(c).pct_change()).fillna(0.0)
    arow, stretches = [], []
    for aa in PAIRS:
        r_p = sl[f"{aa}|parent|0"].reindex(c).pct_change().fillna(0.0)
        # The weight in force on day t was set at an earlier fill; returns on
        # day t are earned by the weight held at the end of day t-1.
        e = {k: exp[f"{aa}|{k}"].shift(1).fillna(0.0) for k in ("n100_and_sc100", "sc100_only", "production_v2")}
        for a_, b_ in (("n100_and_sc100", "sc100_only"), ("n100_and_sc100", "production_v2"),
                       ("sc100_only", "production_v2")):
            dw = e[a_] - e[b_]
            contrib = np.log1p(e[a_] * r_p + (1 - e[a_]) * r_sl) - np.log1p(e[b_] * r_p + (1 - e[b_]) * r_sl)
            arow.append({"aa": aa, "a": a_, "b": b_, "log_gap_total": float(contrib.sum()),
                         "gap_pp_yr": float(np.expm1(contrib.sum() / ((c[-1] - c[0]).days / 365.25)) * 100),
                         "disagree_sessions": int((dw.abs() > 1e-9).sum()),
                         "disagree_share": float((dw.abs() > 1e-9).mean())})
            grp = (dw.abs() > 1e-9).astype(int).diff().ne(0).cumsum()
            for _, g in dw[dw.abs() > 1e-9].groupby(grp[dw.abs() > 1e-9]):
                idx_ = g.index
                stretches.append({"aa": aa, "a": a_, "b": b_, "from": idx_[0].date(), "to": idx_[-1].date(),
                                  "sessions": len(idx_), "a_in_equity": bool(g.iloc[0] > 0),
                                  "parent_return": float((1 + r_p.loc[idx_]).prod() - 1),
                                  "sleeve_return": float((1 + r_sl.loc[idx_]).prod() - 1),
                                  "gold_return": float(gc["gold"].reindex(c).loc[idx_[-1]] /
                                                       gc["gold"].reindex(c).shift(1).loc[idx_[0]] - 1),
                                  "log_contrib": float(contrib.loc[idx_].sum())})
    pd.DataFrame(arow).to_csv(OUT / "attribution_in_sample.csv", index=False)
    stt = pd.DataFrame(stretches)
    stt.to_csv(OUT / "disagreement_stretches.csv", index=False)
    print(f"A done ({time.time() - t0:.0f}s)")

    # ── F. robustness, in-sample, return space on the four books ───────────
    rv = V.window_reviews(V.load_signs())
    ss = sg.reindex(rv)
    rob = []
    for aa in PAIRS:
        r_p = sl[f"{aa}|parent|0"].reindex(c).pct_change().fillna(0.0)
        base_and = run_rs(ss["N100"] * ss["SC100"], r_p, r_sl, c)
        base_sc = run_rs(ss["SC100"], r_p, r_sl, c)
        prod = sl[f"{aa}|production_v2|20.8"].reindex(c)
        rob.append({"aa": aa, "test": "return-space AND", "cagr": cagr(base_and)})
        rob.append({"aa": aa, "test": "return-space SC100 only", "cagr": cagr(base_sc)})
        rob.append({"aa": aa, "test": "simulated current rule", "cagr": cagr(prod)})
        for lag in (1, 2):
            dl = (ss["N100"] * ss["SC100"]).shift(lag).bfill()
            rob.append({"aa": aa, "test": f"AND, {lag}-week delay", "cagr": cagr(run_rs(dl, r_p, r_sl, c))})
            rob.append({"aa": aa, "test": f"SC100 only, {lag}-week delay",
                        "cagr": cagr(run_rs(ss["SC100"].shift(lag).bfill(), r_p, r_sl, c))})
        # circular shifts of the joint (N100, SC100) matrix
        n = len(ss)
        shares = []
        for k in range(8, n - 7):
            sh = pd.DataFrame(np.roll(ss[["N100", "SC100"]].to_numpy(), k, axis=0), index=ss.index, columns=["N100", "SC100"])
            shares.append((cagr(run_rs(sh["N100"] * sh["SC100"], r_p, r_sl, c)),
                           cagr(run_rs(sh["SC100"], r_p, r_sl, c))))
        sh = np.array(shares)
        obs_and = cagr(base_and)
        rob.append({"aa": aa, "test": "shift null: AND percentile", "cagr": float((sh[:, 0] < obs_and).mean())})
        rob.append({"aa": aa, "test": "shift null: share AND > SC100-only", "cagr": float((sh[:, 0] > sh[:, 1]).mean())})
        rob.append({"aa": aa, "test": "shift null: AND median", "cagr": float(np.median(sh[:, 0]))})
        # leave the single best disagreement stretch (vs SC100 only) out
        s_ = stt[(stt.aa == aa) & (stt.a == "n100_and_sc100") & (stt.b == "sc100_only")]
        if len(s_):
            best = s_.sort_values("log_contrib").iloc[-1]
            rob.append({"aa": aa, "test": "AND minus SC100-only, without best stretch (log)",
                        "cagr": float(s_["log_contrib"].sum() - best["log_contrib"])})
            rob.append({"aa": aa, "test": "best stretch share of AND minus SC100-only",
                        "cagr": float(best["log_contrib"] / s_["log_contrib"].sum()) if s_["log_contrib"].sum() else None})
    pd.DataFrame(rob).to_csv(OUT / "robustness_in_sample.csv", index=False)
    print(f"F done ({time.time() - t0:.0f}s)")

    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"all done ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
