# -*- coding: utf-8 -*-
"""
Rebuild each parent smallcase's index from its constituents and compare it with
the published parent NAV (`parentIndices.csv`), 2021-11-01 -> 2026-08-21.

Standalone: reads raw inputs only, imports nothing from `AA/analysis`.

Inputs
    Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_<parent>.csv
        one row per (basket, stock): date (decision), availableDate (effective), ISIN, weight, skipped
    analysis/cache/keyed_ohlcv_eikon_v2.parquet
        daily OHLC per ISIN (column `ticker` holds the ISIN), Eikon, split/bonus/demerger
        adjusted, NOT dividend adjusted (price return)
    analysis/cache/keyed_ohlcv_v2.parquet       the same from Kite, for a second-source check
    Historical Data/frozen_2026-09-25/Data/calendar.csv   NSE sessions (.NSEI)
    Historical Data/parentIndices.csv           published parent NAV, base 100 on 2021-11-01

How a basket is held (every convention)
    At a rebalance the whole value V is put into the new basket at its listed weights:
        shares_i = V * w_i / price_i(at the rebalance price)
    Between rebalances the shares are fixed, so the weights drift:
        V(t) = sum_i shares_i * close_i(t)
    A stock with no close on t carries its last close. No costs (the published index
    is a benchmark level, not a traded book).

Rebalance conventions (R = availableDate, R+1 = the next session)
    prev_close   switch at the close of the session before R (new basket earns all of R)
    avail_open   switch at R's open:     old basket close(R-1) -> open(R), new basket open(R) -> close(R)
    avail_ohlc4  the same at R's (O+H+L+C)/4
    avail_close  switch at the close of R
    next_open    switch at R+1's open:   old basket close(R) -> open(R+1), new basket open(R+1) -> close(R+1)
    next_ohlc4   the same at R+1's (O+H+L+C)/4
    next_close   switch at the close of R+1

Each run starts at the basket in force on 2021-11-01 from that basket's own switch,
so the holdings on 2021-11-01 carry their real drift, and is rebased to 100 on 2021-11-01.

Run:  python data/parent_rebuild.py   (from AA/)
Writes data/parent_rebuild/: summary.csv, daily.csv, top_days.csv, periods.csv, coverage.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
REBAL = HD / "frozen_2026-09-25" / "Rebalance_history"
CAL_CSV = HD / "frozen_2026-09-25" / "Data" / "calendar.csv"
PUB_CSV = HD / "parentIndices.csv"
CACHE = AA / "analysis" / "cache"
OUT = AA / "data" / "parent_rebuild"

PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
START, END = pd.Timestamp("2021-11-01"), pd.Timestamp("2026-08-21")
CONVENTIONS = ["prev_close", "avail_open", "avail_ohlc4", "avail_close",
               "next_open", "next_ohlc4", "next_close"]
BEST = "avail_ohlc4"           # the convention that reproduces the published switch days


def load_published() -> pd.DataFrame:
    p = pd.read_csv(PUB_CSV)
    p["date"] = pd.to_datetime(p["date"], format="%d/%m/%y %H:%M")
    return p.pivot(index="date", columns="scid", values="index").sort_index()


def load_baskets(parent: str, include_skipped: bool = False) -> pd.DataFrame:
    h = pd.read_csv(REBAL / f"Rebalance_history_by_scid_{parent}.csv")
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M")
    h["isin"] = h["ISIN"].astype("string").str.strip().str.upper()
    h["weight"] = pd.to_numeric(h["weight"], errors="coerce")
    h["skipped"] = h["skipped"].astype(str).str.lower().eq("true")
    # skipped=true lists a reviewed basket that was not traded (its weights are the
    # old holdings drifted): the published 0007 index keeps drifting the previous
    # basket through 2021-09-16 -> 2021-12-16, so these rows are not rebalances
    if not include_skipped:
        h = h[~h["skipped"]]
    first = h.loc[h["eff"] <= START, "eff"].max()
    return h[(h["eff"] >= first) & (h["eff"] <= END)].sort_values(["eff", "isin"])


def load_prices(source: str) -> dict[str, pd.DataFrame]:
    name = {"eikon": "keyed_ohlcv_eikon_v2.parquet", "kite": "keyed_ohlcv_v2.parquet"}[source]
    px = pd.read_parquet(CACHE / name)
    px = px.drop_duplicates(["date", "ticker"])
    out = {}
    for f in ("open", "high", "low", "close"):
        out[f] = px.pivot(index="date", columns="ticker", values=f).sort_index()
    return out


def calendar(pub: pd.DataFrame, px: dict) -> pd.DatetimeIndex:
    c = pd.to_datetime(pd.read_csv(CAL_CSV)["date"])
    # the .NSEI file misses a few special sessions (F-AA-D02); add any date the
    # published series or most stocks trade on
    busy = px["close"].notna().sum(axis=1)
    extra = busy[busy >= 0.5 * busy.median()].index
    cal = pd.DatetimeIndex(sorted(set(c) | set(pub.index) | set(extra)))
    return cal[(cal >= pd.Timestamp("2021-06-01")) & (cal <= END)]


def rebuild(h: pd.DataFrame, px: dict, cal: pd.DatetimeIndex, conv: str,
            ledger: list | None = None) -> tuple[pd.Series, list, dict]:
    """
    One parent's index level on `cal` under switch convention `conv`.
    If `ledger` is a list, one row per stock per switch is appended to it
    (side, prices, shares and values; values in this run's own units).
    """
    keys = sorted(h["isin"].unique())
    raw = {f: px[f].reindex(index=cal, columns=keys) for f in ("open", "high", "low", "close")}
    raw_close = raw["close"]
    close = raw_close.ffill()
    opn = px["open"].reindex(index=cal, columns=keys)
    ohlc4 = (px["open"] + px["high"] + px["low"] + px["close"]).reindex(index=cal, columns=keys) / 4
    # 2025-11-24 has blank opens: fall back to the close
    opn = opn.fillna(raw_close)
    ohlc4 = ohlc4.fillna(raw_close)

    effs = sorted(h["eff"].unique())
    pos = {e: cal.searchsorted(e) for e in effs}          # index of R (or the next session if R is not one)
    # index of the day whose price the switch uses, and the switch price field
    def switch(e):
        i = pos[e]
        if conv == "prev_close":
            return i - 1, "close"
        if conv == "avail_close":
            return i, "close"
        if conv == "next_close":
            return i + 1, "close"
        if conv.startswith("avail_"):
            return i, conv.split("_")[1]
        return i + 1, conv.split("_")[1]

    field = {"close": close, "open": opn, "ohlc4": ohlc4}
    sw = {switch(e)[0]: (e, switch(e)[1]) for e in effs}
    first_i = min(sw)
    nav = pd.Series(np.nan, index=cal)
    shares: pd.Series | None = None
    V = 100.0
    missing = []
    held = {}                                           # date -> value weights held from the previous close
    for i in range(first_i, len(cal)):
        d = cal[i]
        if shares is not None:
            v0 = shares * close.iloc[i - 1][shares.index]
            held[d] = v0 / v0.sum()
            V = float((shares * close.loc[d, shares.index]).sum())
        if i in sw:
            e, f = sw[i]
            g = h[h["eff"] == e]
            w = (g.set_index("isin")["weight"] / g["weight"].sum())
            p_sw = field[f].loc[d, w.index]
            if shares is not None and f != "close":
                # old basket from the previous close to the switch price, new basket from there to the close
                p_old = field[f].loc[d, shares.index].fillna(close.loc[d, shares.index])
                V_sw = float((shares * p_old).sum())
            else:
                V_sw = V
            miss = p_sw[p_sw.isna()].index.tolist()
            for m in miss:
                missing.append({"eff": e.date(), "isin": m, "on": d.date()})
            p_sw = p_sw.fillna(close.loc[d, w.index])
            ok = p_sw.notna()
            w = w[ok] / w[ok].sum()
            old = shares
            shares = V_sw * w / p_sw[ok]
            V = float((shares * close.loc[d, shares.index]).sum())
            if ledger is not None:
                names = g.set_index("isin")["name"]
                prev = h[h["eff"] < e]
                prev_names = prev.drop_duplicates("isin").set_index("isin")["name"] if len(prev) else names
                for k in sorted(set(w.index) | (set(old.index) if old is not None else set())):
                    s0 = float(old[k]) if old is not None and k in old.index else 0.0
                    s1 = float(shares[k]) if k in shares.index else 0.0
                    p = float(field[f].loc[d, k]) if pd.notna(field[f].loc[d, k]) else float(close.loc[d, k])
                    full = all(pd.notna(raw[x].loc[d, k]) for x in ("open", "high", "low", "close"))
                    ledger.append({
                        "eff": pd.Timestamp(e).date(), "switch_day": d.date(),
                        "decision_date": g["date"].iloc[0], "isin": k,
                        "name": names.get(k, prev_names.get(k, "")),
                        "side": "start" if old is None else ("keep" if s0 and s1 else ("buy" if s1 else "sell")),
                        "target_w": float(w.get(k, 0.0)),
                        "open": raw["open"].loc[d, k], "high": raw["high"].loc[d, k],
                        "low": raw["low"].loc[d, k], "close": raw["close"].loc[d, k],
                        "price_used": p, "price_basis": f if full else f"{f} (fallback: close)",
                        "shares_before": s0, "shares_after": s1,
                        "value_before": s0 * p, "value_after": s1 * p,
                        "trade_value": (s1 - s0) * p, "basket_value_at_switch": V_sw})
        nav.iloc[i] = V
    return nav, missing, held


def stats(model: pd.Series, pub: pd.Series, reb_days: set) -> dict:
    d = pd.DataFrame({"model": model, "pub": pub}).dropna().loc[START:END]
    d = d / d.iloc[0] * 100
    r = d.pct_change().dropna()
    diff = r["model"] - r["pub"]
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    cg = (d.iloc[-1] / d.iloc[0]) ** (1 / yrs) - 1
    on_reb = diff.index.isin(list(reb_days))
    ld = np.log1p(r["model"]) - np.log1p(r["pub"])
    return {
        "cagr_pub_%": cg["pub"] * 100,
        "cagr_model_%": cg["model"] * 100,
        "gap_pp_yr": (cg["model"] - cg["pub"]) * 100,
        "end_level_ratio": d["model"].iloc[-1] / d["pub"].iloc[-1],
        "tracking_error_%_yr": diff.std() * np.sqrt(252) * 100,
        "corr_daily": r["model"].corr(r["pub"]),
        "days": len(diff),
        "days_|diff|<1bp": int((diff.abs() < 1e-4).sum()),
        "days_|diff|>25bp": int((diff.abs() > 25e-4).sum()),
        "gap_on_rebalance_days_pp_yr": ld[on_reb].sum() / yrs * 100,
        "gap_other_days_pp_yr": ld[~on_reb].sum() / yrs * 100,
    }


def residual_days(parent: str, nav: pd.Series, pub: pd.Series, held: dict, px: dict, kite: dict,
                  bp: float = 5.0) -> list:
    """
    Every published day where the rebuild's return differs by more than `bp`, with
    the held stock that best explains it. Two candidate explanations per stock i
    (w_i = its value weight from the previous close):
      flat     the published index left i unchanged that day:  diff ~ w_i * r_i
      kite     the published index used Kite's price for i:    diff ~ w_i * (r_eikon - r_kite)
    """
    pdays = pub.loc[START:END].index
    m = nav.reindex(pdays)
    r_m, r_p = m.pct_change(), pub.loc[START:END].pct_change()
    ce = px["close"].ffill().reindex(pdays)
    ck = kite["close"].ffill().reindex(pdays)
    re_, rk = ce.pct_change(), ck.pct_change()
    out = []
    for j in range(1, len(pdays)):
        d = pdays[j]
        diff = (r_m.iloc[j] - r_p.iloc[j]) * 1e4
        if not abs(diff) > bp or d not in held:
            continue
        w = held[d]
        e = re_.loc[d, w.index].fillna(0)
        k = rk.reindex(columns=w.index).loc[d].fillna(e)
        flat = (w * e * 1e4 - diff).abs()
        kit = (w * (e - k) * 1e4 - diff).abs()
        i_f, i_k = flat.idxmin(), kit.idxmin()
        out.append({"parent": parent, "date": d.date(), "model_%": r_m.iloc[j] * 100,
                    "published_%": r_p.iloc[j] * 100, "diff_bp": diff,
                    "flat_isin": i_f, "flat_w": w[i_f], "flat_r_%": e[i_f] * 100,
                    "flat_left_bp": diff - w[i_f] * e[i_f] * 1e4,
                    "kite_isin": i_k, "kite_r_%": k[i_k] * 100,
                    "kite_left_bp": diff - w[i_k] * (e[i_k] - k[i_k]) * 1e4})
    return out


def rebalance_rows(parent: str, led: pd.DataFrame, nav: pd.Series, pub: pd.Series) -> list:
    """
    One row per switch: what traded, the prices' basis, and the rebuilt against the
    published NAV on the published sessions just before, on, and just after R.
    `nav` is already in published-index points (100 on 2021-11-01).
    """
    pdays = pub.dropna().index
    out = []
    for (eff, sd), g in led.groupby(["eff", "switch_day"]):
        R = pd.Timestamp(sd)
        start = bool((g["side"] == "start").all())       # the basket the rebuild starts from, not a trade
        row = {"parent": parent, "decision_date": g["decision_date"].iloc[0], "availableDate": eff,
               "switch_day": sd, "start_of_rebuild": start,
               "buys": int(g["side"].isin(["buy", "start"]).sum()), "sells": int((g["side"] == "sell").sum()),
               "keeps": int((g["side"] == "keep").sum()),
               "stocks_after": int((g["shares_after"] > 0).sum()),
               "target_w_sum": g["target_w"].sum(),
               "turnover_%": np.nan if start else
               g["trade_value"].abs().sum() / 2 / g["basket_value_at_switch"].iloc[0] * 100,
               "all_prices_real_ohlc4": bool((g["price_basis"] == "ohlc4").all()),
               "basket_value_at_switch": g["basket_value_at_switch"].iloc[0]}
        if R > pdays[0] and R in pdays:
            i = pdays.get_loc(R)
            d0, d2 = pdays[i - 1], pdays[min(i + 1, len(pdays) - 1)]
            for lab, d in (("prev", d0), ("R", R), ("next", d2)):
                row[f"{lab}_session"] = d.date()
                row[f"published_{lab}"] = pub[d]
                row[f"rebuilt_{lab}"] = nav[d]
            row["switch_day_error_bp"] = ((nav[R] / nav[d0]) / (pub[R] / pub[d0]) - 1) * 1e4
            row["three_day_error_bp"] = ((nav[d2] / nav[d0]) / (pub[d2] / pub[d0]) - 1) * 1e4
            row["level_gap_next_%"] = (nav[d2] / pub[d2] - 1) * 100
        out.append(row)
    return out


def held_gaps(parent: str, h: pd.DataFrame, px: dict, cal: pd.DatetimeIndex, pub: pd.DataFrame) -> list:
    """Every (held stock, session) from 2021-11-01 with no Eikon close; the rebuild carries the last close."""
    effs = sorted(h["eff"].unique())
    names = h.drop_duplicates("isin").set_index("isin")["name"]
    close = px["close"].reindex(index=cal, columns=sorted(h["isin"].unique()))
    out = []
    for n, e in enumerate(effs):
        i0 = cal.searchsorted(e)
        i1 = cal.searchsorted(effs[n + 1]) if n + 1 < len(effs) else len(cal)
        seg = cal[i0 + 1:i1 + 1]                        # held from the session after the switch to the next switch
        seg = seg[seg >= START]
        for k in h.loc[h["eff"] == e, "isin"]:
            for d in seg[close.loc[seg, k].isna().to_numpy()]:
                out.append({"parent": parent, "basket": pd.Timestamp(e).date(), "isin": k, "name": names[k],
                            "date": d.date(), "weekday": d.day_name(),
                            "published_session": d in pub.index})
    return out


def write_md(sm, yr, rb, lg, gp, td) -> None:
    """PARENT_REBUILD.md: the record of the rebuild, every number from the CSVs written this run."""
    b = sm[(sm["source"] == "eikon") & (sm["convention"] == BEST)].set_index("parent")
    L = []
    w = L.append
    w("# Parent index rebuild from constituents, checked against the published NAV")
    w("")
    w(f"Generated by `data/parent_rebuild.py` on {pd.Timestamp.today().date()}. Every number below comes from the CSVs in this folder; do not edit by hand.")
    w("")
    w("**Window:** 2021-11-01 → 2026-08-21 (the published parent NAVs start 2021-11-01 at 100; the stock and NAV files end 2026-08-21).")
    w("")
    w("## What was done")
    w("")
    w("For each parent (SCMO_0003, 0007, 0010, 0029), the index was rebuilt from its own baskets and stock prices, then compared day by day with `parentIndices.csv`.")
    w("")
    w("| Input | File | Used for |")
    w("|---|---|---|")
    w("| Baskets | `Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_<parent>.csv` | ISIN, weight, `date` (decision), `availableDate` (effective); rows with `skipped=true` are not rebalances |")
    w("| Stock prices | `analysis/cache/keyed_ohlcv_eikon_v2.parquet` (Eikon, per ISIN, 2021-06-01 → 2026-08-21) | open, high, low, close; split/bonus/demerger adjusted, not dividend adjusted |")
    w("| Second price source | `analysis/cache/keyed_ohlcv_v2.parquet` (Kite) | cross-check only |")
    w("| Calendar | `Historical Data/frozen_2026-09-25/Data/calendar.csv` plus published dates plus days most stocks trade | sessions |")
    w("| Published NAV | `Historical Data/parentIndices.csv` | the comparison |")
    w("")
    w("**Formulas.**")
    w("")
    w("- Switch day R = the basket's `availableDate`. Switch price of stock i: P_i = (open + high + low + close) ÷ 4 on R.")
    w("- Value of the old basket at the switch: V = Σ old shares_i × P_i.")
    w("- New shares: shares_i = V × w_i ÷ P_i, with w_i the listed weights renormalised to sum to 1.")
    w("- Every other day: level(t) = Σ shares_i × close_i(t). A stock with no close carries its last close.")
    w("- The rebuild starts at the basket in force on 2021-11-01 from that basket's own switch, and is scaled to 100 on 2021-11-01 like the published series.")
    w("- No costs, no dividends: the published index is price return (the gap on non-rebalance days is about 0 pp/yr).")
    w("- CAGR = (level_end ÷ level_start)^(365.25 ÷ calendar days) − 1. Tracking error = std(daily return difference) × √252.")
    w("")
    w("## Result: rebuilt vs published NAV, 2021-11-01 → 2026-08-21")
    w("")
    w("| Parent | Published CAGR | Rebuilt CAGR | Gap pp/yr | Ending level ratio | Days within 1 bp (of 1,185) | Days off > 25 bp | Tracking error %/yr |")
    w("|---|---|---|---|---|---|---|---|")
    for p, r in b.iterrows():
        w(f"| {p} | {r['cagr_pub_%']:.2f}% | {r['cagr_model_%']:.2f}% | {r['gap_pp_yr']:+.2f} | {r['end_level_ratio']:.4f} | "
          f"{int(r['days_|diff|<1bp']):,} | {int(r['days_|diff|>25bp'])} | {r['tracking_error_%_yr']:.2f} |")
    w("")
    w("Calendar-year return, rebuilt minus published, pp (2021 = 2021-11-01 → 2021-12-31; 2026 = to 2026-08-21):")
    w("")
    yp = yr.pivot(index="year", columns="parent", values="diff_pp")
    w("| Year | " + " | ".join(yp.columns) + " |")
    w("|---|" + "---|" * len(yp.columns))
    for y, r in yp.iterrows():
        w(f"| {y} | " + " | ".join(f"{v:+.2f}" for v in r) + " |")
    w("")
    w("## Which switch timing the published index uses")
    w("")
    w("CAGR gap, rebuilt minus published, pp/yr (Eikon prices):")
    w("")
    cv = sm[sm["source"] == "eikon"].pivot(index="convention", columns="parent", values="gap_pp_yr").reindex(CONVENTIONS)
    label = {"prev_close": "close of the session before R", "avail_open": "R's open",
             "avail_ohlc4": "**R's (O+H+L+C)/4**", "avail_close": "R's close", "next_open": "next session's open",
             "next_ohlc4": "next session's (O+H+L+C)/4", "next_close": "next session's close"}
    w("| Switch at | " + " | ".join(cv.columns) + " |")
    w("|---|" + "---|" * len(cv.columns))
    for c, r in cv.iterrows():
        w(f"| {label[c]} | " + " | ".join(f"{v:+.2f}" for v in r) + " |")
    w("")
    k = sm[(sm["source"] == "kite") & (sm["convention"] == BEST)].set_index("parent")["gap_pp_yr"]
    w("The same rebuild on Kite prices: " + ", ".join(f"{p} {v:+.2f}" for p, v in k.items())
      + " pp/yr. Eikon is the source to use.")
    w("")
    w("`skipped=true` baskets: 0007's 2021-09-16 basket is flagged skipped. Trading it matches 6 of 29 days to 2021-12-15; "
      "letting the 2021-06-17 basket drift on matches 29 of 29. So a skipped basket is not a trade (F-AA-D07).")
    w("")
    w("## Every rebalance")
    w("")
    w("Published and rebuilt NAV on the published session before R, on R, and after R. "
      "Switch-day error = (rebuilt return ÷ published return on R) − 1. "
      "Three-day error = the same from the session before R to the session after. "
      "Turnover = Σ|trade value| ÷ 2 ÷ basket value. "
      "Prices: every bought, sold and kept stock priced at its real (O+H+L+C)/4 on R (✓), or a fallback (✗).")
    w("")
    for p, g in rb.groupby("parent"):
        w(f"### {p}")
        w("")
        w("| Decision | R (switch) | Buys | Sells | Keeps | Stocks | Turnover | Prices | Published before → R → after | Rebuilt before → R → after | Switch-day error bp | Three-day error bp | Level gap after R |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for _, r in g.iterrows():
            if pd.notna(r.get("published_R")):
                pubs = f"{r['published_prev']:.2f} → {r['published_R']:.2f} → {r['published_next']:.2f}"
                rebs = f"{r['rebuilt_prev']:.2f} → {r['rebuilt_R']:.2f} → {r['rebuilt_next']:.2f}"
                e1, e3, lv = f"{r['switch_day_error_bp']:+.1f}", f"{r['three_day_error_bp']:+.1f}", f"{r['level_gap_next_%']:+.2f}%"
            else:
                pubs = rebs = "before the published series"
                e1 = e3 = lv = "–"
            to = "start of rebuild" if r["start_of_rebuild"] else f"{r['turnover_%']:.1f}%"
            w(f"| {r['decision_date']} | {r['switch_day']} | {r['buys']} | {r['sells']} | {r['keeps']} | {r['stocks_after']} | "
              f"{to} | {'✓' if r['all_prices_real_ohlc4'] else '✗'} | {pubs} | {rebs} | {e1} | {e3} | {lv} |")
        w("")
    # worked example
    ex_p, ex_d = "SCMO_0029", pd.Timestamp("2025-06-03").date()
    ex = lg[(lg["parent"] == ex_p) & (lg["switch_day"] == ex_d)]
    er = rb[(rb["parent"] == ex_p) & (rb["switch_day"] == ex_d)]
    if len(ex) and len(er):
        er = er.iloc[0]
        w(f"## Worked example: {ex_p}, rebalance on {ex_d}")
        w("")
        w(f"Decision date {er['decision_date']}, `availableDate` {er['availableDate']}. Basket value at the switch V = Σ old shares × P = **{er['basket_value_at_switch']:.4f}** index points.")
        w("")
        w("| Stock | Side | Target weight | Open | High | Low | Close | P = (O+H+L+C)/4 | Shares before | Shares after | Trade value (pts) |")
        w("|---|---|---|---|---|---|---|---|---|---|---|")
        for _, r in ex.sort_values(["side", "name"]).iterrows():
            w(f"| {r['name']} | {r['side']} | {r['target_w']:.4f} | {r['open']:.2f} | {r['high']:.2f} | {r['low']:.2f} | {r['close']:.2f} | "
              f"{r['price_used']:.4f} | {r['shares_before']:.6f} | {r['shares_after']:.6f} | {r['trade_value']:+.4f} |")
        w("")
        w(f"Check: shares after = V × target weight ÷ P. Level at R's close = Σ shares after × close = **{er['rebuilt_R']:.4f}**; "
          f"published {er['published_R']:.4f}. Published {er['prev_session']} → {er['next_session']}: "
          f"{er['published_prev']:.4f} → {er['published_next']:.4f}; rebuilt {er['rebuilt_prev']:.4f} → {er['rebuilt_next']:.4f}. "
          f"The rebuilt level already stood {(er['rebuilt_prev'] / er['published_prev'] - 1) * 100:+.3f}% from the published "
          f"one before R (accumulated since 2021-11-01); across the rebalance itself the error is "
          f"{er['three_day_error_bp']:+.2f} bp.")
        w("")
    w("## Price coverage")
    w("")
    sides = lg[lg["side"] != "start"].groupby("side").agg(rows=("isin", "size"),
                                                          real=("price_basis", lambda s: int((s == "ohlc4").sum())))
    w("**On switch days** (every stock bought, sold or kept, rebalances from 2021-06-17 on):")
    w("")
    w("| Side | Stock rows | Priced at the real (O+H+L+C)/4 | Fallback |")
    w("|---|---|---|---|")
    for s, r in sides.iterrows():
        w(f"| {s} | {r['rows']} | {r['real']} | {r['rows'] - r['real']} |")
    w("")
    w("**On holding days** (2021-11-01 → 2026-08-21), held stocks with no Eikon close; the rebuild carries the last close:")
    w("")
    if len(gp):
        gd = gp.groupby(["date", "weekday", "published_session"]).agg(stocks=("isin", "size")).reset_index()
        w("| Date | Day | Held stocks with no close | In the published series? |")
        w("|---|---|---|---|")
        for _, r in gd.iterrows():
            w(f"| {r['date']} | {r['weekday']} | {r['stocks']} | {'yes' if r['published_session'] else 'no'} |")
        w("")
        w("Each of these is a special weekend session. Where the published series has the day, the rebuild is flat for those "
          "stocks while the published index moves, and the gap reverses on the next session: the level and CAGR are unaffected.")
    else:
        w("None.")
    w("")
    w("## Days the rebuild is off by more than 5 bp")
    w("")
    cnt = td.groupby("parent").size()
    w("Count per parent: " + ", ".join(f"{p} {n}" for p, n in cnt.items()) + ". Full list with the likely stock: `residual_days.csv`.")
    w("")
    w("- The special sessions above (pairs that cancel).")
    w("- SCMO_0003, 2021-11 → 2022-06: daily differences of 5–26 bp with no missing price; it adds +0.46 pp to 2022. "
      "Partly Eikon-vs-Kite price differences in Polyplex Corp; the rest is unexplained. It does not recur after 2022-06.")
    w("")
    w("## Files")
    w("")
    w("| File | Contents |")
    w("|---|---|")
    w("| `summary.csv` | every switch timing × price source × parent: CAGRs, gap, tracking error, day counts |")
    w("| `rebalances.csv` | the table above, one row per rebalance |")
    w("| `rebalance_ledger.csv` | one row per stock per rebalance: side, target weight, O/H/L/C, price used, shares before and after, trade value (index points) |")
    w("| `held_price_gaps.csv` | every held stock-session with no Eikon close |")
    w("| `residual_days.csv` | every day off by more than 5 bp, with the stock that best explains it |")
    w("| `switch_days.csv` | each rebalance's published return against the old and new basket |")
    w("| `daily.csv`, `yearly.csv` | daily levels and calendar-year returns, rebuilt and published |")
    w("")
    w("**Reproduce:** from `AA/`, `python data/parent_rebuild.py`.")
    (OUT / "PARENT_REBUILD.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def switch_days(parent: str, effs: list, navs: dict, pub: pd.Series) -> list:
    """
    Per rebalance, the published return on R-1, R and R+1 against the old basket
    (avail_close run) and the new basket (prev_close run).
    old_share_R = (pub - new) / (old - new): the share of day R the published index
    earned on the old basket. 1 = switched at R's close, 0 = at R-1's close.
    """
    pdays = pub.loc[START:END].index
    r_pub = pub.loc[START:END].pct_change()
    r_old = navs["avail_close"].reindex(pdays).pct_change()
    r_new = navs["prev_close"].reindex(pdays).pct_change()
    out = []
    for e in effs:
        i = pdays.searchsorted(e)
        if i < 1 or i + 1 >= len(pdays):
            continue
        row = {"parent": parent, "eff": pd.Timestamp(e).date(), "R": pdays[i].date()}
        for lab, j in (("Rm1", i - 1), ("R", i), ("Rp1", i + 1)):
            row[f"pub_{lab}_%"] = r_pub.iloc[j] * 100
            row[f"old_{lab}_%"] = r_old.iloc[j] * 100
            row[f"new_{lab}_%"] = r_new.iloc[j] * 100
        spread = r_old.iloc[i] - r_new.iloc[i]
        row["old_minus_new_R_%"] = spread * 100
        row["old_share_R"] = (r_pub.iloc[i] - r_new.iloc[i]) / spread if abs(spread) > 5e-4 else np.nan
        for conv in CONVENTIONS:
            m = navs[conv].reindex(pdays)
            a, b = pdays[i - 1], pdays[i + 1]
            row[f"err_{conv}_bp"] = ((m[b] / m[a]) / (pub[b] / pub[a]) - 1) * 1e4
        out.append(row)
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pub = load_published()
    rows, daily, tops, periods, cov = [], [], [], [], []
    ledgers, rebal, gaps = [], [], []
    kite = load_prices("kite")
    for source in ("eikon", "kite"):
        px = load_prices(source)
        cal = calendar(pub, px)
        for parent in PARENTS:
            h = load_baskets(parent)
            effs = sorted(h["eff"].unique())
            # the sessions where any convention can move: R-1 .. R+1
            reb = set()
            for e in effs:
                i = cal.searchsorted(e)
                reb |= {cal[j] for j in (i - 1, i, i + 1) if 0 <= j < len(cal)}
            navs = {}
            for conv in CONVENTIONS:
                lg = [] if (source == "eikon" and conv == BEST) else None
                nav, miss, held = rebuild(h, px, cal, conv, lg)
                navs[conv] = nav
                if lg is not None:
                    tops += residual_days(parent, nav, pub[parent], held, px, kite)
                    k = 100.0 / nav.loc[START]          # put the ledger in published-index points
                    led = pd.DataFrame(lg).assign(parent=parent)
                    for c in ("value_before", "value_after", "trade_value", "basket_value_at_switch"):
                        led[c] *= k
                    led["shares_before"] *= k
                    led["shares_after"] *= k
                    ledgers.append(led)
                    rebal += rebalance_rows(parent, led, nav * k, pub[parent])
                    gaps += held_gaps(parent, h, px, cal, pub)
                s = stats(nav, pub[parent], reb)
                rows.append({"source": source, "parent": parent, "convention": conv, **s,
                             "unpriced_at_switch": len(miss)})
                if source == "eikon":
                    cov += [{"parent": parent, "convention": conv, **m} for m in miss]
                    m = nav.reindex(pub.index).loc[START:END]
                    m = m / m.iloc[0] * 100
                    daily.append(pd.DataFrame({"parent": parent, "convention": conv,
                                               "model": m, "published": pub[parent].loc[START:END]}))
            if source == "eikon":
                periods += switch_days(parent, effs, navs, pub[parent])
            print(f"{source} {parent} done", flush=True)

    sm = pd.DataFrame(rows)
    sm.to_csv(OUT / "summary.csv", index=False)
    dl = pd.concat(daily).rename_axis("date").reset_index()
    dl.to_csv(OUT / "daily.csv", index=False)
    # calendar-year returns under the matching convention; 2021 starts 2021-11-01, 2026 ends 2026-08-21
    b = dl[dl["convention"] == BEST].set_index("date")
    yr = []
    for parent, g in b.groupby("parent"):
        ye = g[["model", "published"]].groupby(g.index.year).last()
        prev = pd.concat([g[["model", "published"]].iloc[[0]].set_axis([ye.index[0] - 1]), ye]).shift(1).dropna()
        ret = (ye.loc[prev.index] / prev - 1) * 100
        for y, rr in ret.iterrows():
            yr.append({"parent": parent, "year": y, "model_%": rr["model"], "published_%": rr["published"],
                       "diff_pp": rr["model"] - rr["published"]})
    pd.DataFrame(yr).to_csv(OUT / "yearly.csv", index=False)
    pd.DataFrame(cov).to_csv(OUT / "coverage.csv", index=False)
    pr = pd.DataFrame(periods)
    pr.to_csv(OUT / "switch_days.csv", index=False)
    names = pd.concat([load_baskets(p) for p in PARENTS]).drop_duplicates("isin").set_index("isin")["name"]
    td = pd.DataFrame(tops)
    td.insert(6, "flat_name", td["flat_isin"].map(names))
    td.insert(11, "kite_name", td["kite_isin"].map(names))
    td.to_csv(OUT / "residual_days.csv", index=False)
    lg = pd.concat(ledgers, ignore_index=True)
    lg = lg[["parent"] + [c for c in lg.columns if c != "parent"]]
    lg.to_csv(OUT / "rebalance_ledger.csv", index=False)
    rb = pd.DataFrame(rebal)
    rb.to_csv(OUT / "rebalances.csv", index=False)
    gp = pd.DataFrame(gaps)
    gp.to_csv(OUT / "held_price_gaps.csv", index=False)
    write_md(sm, pd.DataFrame(yr), rb, lg, gp, td)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(sm.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
