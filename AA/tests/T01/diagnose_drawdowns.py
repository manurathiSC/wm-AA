"""
T01 diagnostic, added after the run (2026-10-05). Descriptive only: no claims, no criteria.

Question (the user, on the path chart): "these look huge drawdowns, why didn't we exit at the
right time for these?" For every fall of the parent index of 15% or more inside each window,
measure when each rule got out, how much of the fall had already happened, how often it bought
back in before the bottom, and how much of the rebound it missed.

Reads only shipped evidence: evidence/headline/spliced_inputs.csv and decisions_all_configs.csv.
The held state is the equity target from each traded decision, effective at its trade session's
close (T01.md §3 step 6). "Equity fall sat through" = prod(1 + e_{t-1} r_t) - 1 over the fall,
i.e. the parent's fall weighted by the weight the rule held in it; it ignores the sleeve's own
return and costs.

    python AA/tests/T01/diagnose_drawdowns.py   ->  evidence/diagnostics/drawdown_episodes.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence" / "headline"
OUT = HERE / "evidence" / "diagnostics"
OUT.mkdir(parents=True, exist_ok=True)
PARENT = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
WIN = {"W1": ("2015-07-31", "2021-10-29"), "W2": ("2021-11-01", "2026-08-21")}
CONFIGS = ["pct_w65_q25", "pct_w65_hyst", "pct_w65_q25_daily", "ddhigh_250_x10", "sma_200", "st_weekly", "triple"]
DEPTH = -0.15


def episodes(p: pd.Series, depth: float):
    """Peak-to-trough falls of at least `depth` (negative); a fall ends when P regains its peak."""
    out, peak_i, i = [], 0, 1
    v = p.to_numpy()
    while i < len(v):
        if v[i] >= v[peak_i]:
            peak_i = i
            i += 1
            continue
        j = i
        while j < len(v) and v[j] < v[peak_i]:
            j += 1
        seg = slice(peak_i, j)
        tr = peak_i + int(np.argmin(v[seg]))
        if v[tr] / v[peak_i] - 1 <= depth:
            out.append((peak_i, tr, j if j < len(v) else None))
        peak_i, i = (j, j + 1) if j < len(v) else (len(v) - 1, len(v))
    return out


def held_state(dec: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    """Equity weight held at each session's close."""
    st = pd.Series(np.nan, index=cal)
    for r in dec[dec.traded].itertuples():
        st.loc[r.trade_session] = r.equity_target
    return st.ffill().fillna(0.0)          # 0 before the build: the book is in cash at T0


def main():
    s = pd.read_csv(EV / "spliced_inputs.csv", parse_dates=["date"]).set_index("date")
    d = pd.read_csv(EV / "decisions_all_configs.csv", parse_dates=["decision_date", "trade_session"])
    d["traded"] = d["traded"].astype(str).str.lower().eq("true")
    rows = []
    for book, par in PARENT.items():
        for w, (a, b) in WIN.items():
            p = s.loc[a:b, f"P_{par}"]
            cal = p.index
            r = p.pct_change().fillna(0.0)
            for k, (pi, ti, ri) in enumerate(episodes(p, DEPTH), 1):
                peak, trough = cal[pi], cal[ti]
                rec = cal[ri] if ri is not None else None
                for c in CONFIGS:
                    e = held_state(d[(d.config == c) & (d.book == book) & (d.window == w)], cal)
                    fall = e.loc[peak:trough]
                    # first session after the peak at which the rule held < 1 in equity
                    out_days = fall.index[(fall < 1.0) & (fall.index > peak)]
                    in_at_peak = e.loc[peak] >= 1.0
                    first_out = out_days[0] if len(out_days) else None
                    # buy-backs before the trough: switches from < 1 to 1 inside (first_out, trough]
                    seg = e.loc[first_out:trough] if first_out is not None else e.iloc[:0]
                    buybacks = int(((seg >= 1.0) & (seg.shift(1) < 1.0)).sum())
                    # back in after the trough
                    after = e.loc[trough:]
                    back = after.index[(after >= 1.0) & (after.index > trough)]
                    back_in = back[0] if len(back) and e.loc[trough] < 1.0 else (trough if e.loc[trough] >= 1.0 else None)
                    ex = e.shift(1).loc[peak:trough].iloc[1:]
                    rr = r.loc[peak:trough].iloc[1:]
                    rows.append({
                        "book": book, "parent": par, "window": w, "episode": k,
                        "peak": peak.date(), "trough": trough.date(), "recovered": rec.date() if rec is not None else "not by window end",
                        "fall": p.iloc[ti] / p.iloc[pi] - 1, "sessions_peak_to_trough": ti - pi,
                        "config": c, "in_equity_at_peak": bool(in_at_peak),
                        "first_out": first_out.date() if first_out is not None else None,
                        "fall_done_at_first_out": (p.loc[first_out] / p.iloc[pi] - 1) if first_out is not None else np.nan,
                        "share_of_fall_before_out": ((p.iloc[pi] - p.loc[first_out]) / (p.iloc[pi] - p.iloc[ti])) if first_out is not None else np.nan,
                        "buybacks_before_trough": buybacks,
                        "share_sessions_out": float((1 - ex).mean()),
                        "equity_fall_sat_through": float(np.prod(1 + ex.to_numpy() * rr.to_numpy()) - 1),
                        "back_in": back_in.date() if back_in is not None else None,
                        "rebound_missed": (p.loc[back_in] / p.iloc[ti] - 1) if back_in is not None else np.nan,
                    })
    E = pd.DataFrame(rows)
    E.to_csv(OUT / "drawdown_episodes.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
    f = lambda x: f"{x * 100:+.1f}%" if pd.notna(x) else "–"
    R = E[E.config == "pct_w65_q25"].copy()
    print(f"Falls of {abs(DEPTH):.0%} or more, by book and window; your rule (pct_w65_q25, weekly):")
    show = R[["window", "book", "peak", "trough", "fall", "first_out", "fall_done_at_first_out", "share_of_fall_before_out",
              "buybacks_before_trough", "share_sessions_out", "equity_fall_sat_through", "back_in", "rebound_missed"]].copy()
    for col in ("fall", "fall_done_at_first_out", "equity_fall_sat_through", "rebound_missed", "share_sessions_out", "share_of_fall_before_out"):
        show[col] = show[col].map(f)
    print(show.to_string(index=False))
    print("\nAverage over all falls (each fall counts once per book):")
    g = E.groupby("config", sort=False).agg(falls=("fall", "size"), avg_fall=("fall", "mean"),
                                            avg_fall_done_at_exit=("fall_done_at_first_out", "mean"),
                                            avg_share_before_exit=("share_of_fall_before_out", "mean"),
                                            avg_buybacks=("buybacks_before_trough", "mean"),
                                            avg_share_out=("share_sessions_out", "mean"),
                                            avg_sat_through=("equity_fall_sat_through", "mean"),
                                            avg_rebound_missed=("rebound_missed", "mean"))
    print(g.round(3).to_string())
    for w in ("W1", "W2"):
        print(f"\n{w} only:")
        print(E[E.window == w].groupby("config", sort=False)[["fall", "fall_done_at_first_out", "buybacks_before_trough", "share_sessions_out",
                                                               "equity_fall_sat_through", "rebound_missed"]].mean().round(3).to_string())


if __name__ == "__main__":
    main()
