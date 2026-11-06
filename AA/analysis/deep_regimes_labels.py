# -*- coding: utf-8 -*-
"""
Deep regimes, part 1: weekly regime labels.

All labels live on the weekly review grid (the Friday review dates of the
production Master_* files; one per week, 5-9 days apart). Closes are the
index close at the last session on or before each review date ("Friday
closes").

  R1 (HINDSIGHT)  market phase, separately for SC100 and N100:
        bear       = weeks after a peak up to and including the trough of a
                     decline that reached >= 20% from that peak before the
                     peak was regained;
        correction = the same for a decline of 10-20%;
        recovery   = weeks after such a trough up to and including the week
                     the index first closes back at or above that peak (or
                     the end of data if it has not);
        bull       = everything else.
     Declines are measured from the running maximum. Inside every recovery
     the same rule is applied again from the trough (running max reset), so
     a nested decline of 10%+ inside a long recovery (e.g. SC100 2010-11,
     inside the recovery from the 2008 crash) gets its own bear/correction
     and recovery labels. Uses the whole future path: ex post only.
  R2 (ex ante)    SC100 close above / below its 40-week moving average
                  (the mean of the last 40 weekly closes, current included).
  R3 (ex ante)    SC100 13-week realised volatility (std of the last 13
                  weekly log returns x sqrt(52)); tercile thresholds are the
                  33.3% / 66.7% quantiles of ALL PAST weekly vol values
                  (strictly before this week, expanding, min 52 values).
  R4 (ex ante)    SC100 26-week return minus N100 26-week return:
                  small-led > +5pp, large-led < -5pp, else neutral.
  R5 (ex ante)    signal state: both BUY / only N100 BUY / only SC100 BUY /
                  both SELL.
  R6 (ex ante)    breadth: number of N50, N100, MC100, SC100 that are BUY.

Writes evidence/why_n100sc100/deep/regimes_weekly_labels.csv and
regimes_phase_episodes.csv.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import why_n100sc100 as W
from triple_and_test import index_levels

DEEP = W.OUT / "deep"
os.makedirs(DEEP, exist_ok=True)
END = pd.Timestamp("2026-08-21")
BEAR, CORR = 0.20, 0.10


def _episodes(x: pd.Series, lab: pd.Series, eps: list, idx: str, level: int) -> None:
    """Label the declines of x (a weekly close series) in place, recursing into recoveries."""
    m = x.cummax()
    dd = x / m - 1
    below = (dd < -1e-12).to_numpy()
    n, i = len(x), 0
    while i < n:
        if not below[i]:
            i += 1
            continue
        j = i
        while j < n and below[j]:
            j += 1
        # weeks i .. j-1 are below the peak set at week i-1; week j is back at/above it
        t = i + int(np.argmin(x.iloc[i:j].to_numpy()))
        peak_val = float(m.iloc[i])
        depth = float(x.iloc[t] / peak_val - 1)
        if depth <= -CORR:
            kind = "bear" if depth <= -BEAR else "correction"
            lab.iloc[i:t + 1] = kind
            rec_last = min(j, n - 1)                     # inclusive
            if t + 1 <= rec_last:
                lab.iloc[t + 1:rec_last + 1] = "recovery"
            eps.append({"index": idx, "level": level, "kind": kind,
                        "peak": x.index[i - 1].date(), "trough": x.index[t].date(),
                        "recovered": x.index[j].date() if j < n else None,
                        "peak_close": peak_val, "trough_close": float(x.iloc[t]),
                        "depth": depth, "weeks_down": t - (i - 1),
                        "weeks_recovery": (j - t) if j < n else None})
            # nested declines inside the recovery, running max reset at the trough
            sub = x.iloc[t:rec_last + 1]
            sub_lab = lab.iloc[t:rec_last + 1].copy()
            _episodes(sub, sub_lab, eps, idx, level + 1)
            lab.iloc[t:rec_last + 1] = sub_lab.to_numpy()
        i = j


def phase_labels(x: pd.Series, idx: str):
    x = x.dropna()
    lab = pd.Series("bull", index=x.index, dtype=object)
    eps: list = []
    _episodes(x, lab, eps, idx, 0)
    return lab, eps


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    cal = W.calendar()
    cal = cal[cal <= END]
    sg = W.weekly_signs()
    sg = sg[sg.index <= END]
    lv = index_levels(cal)
    # the weekly grid: every review date with an SC100 signal (weekly from 2004)
    g = sg.index[sg["SC100"].notna()]
    px = lv[["N50", "N100", "MC100", "SC100"]].reindex(g, method="ffill")
    out = pd.DataFrame(index=g)
    out.index.name = "review"
    out["SC100_close"] = px["SC100"]
    out["N100_close"] = px["N100"]

    # R1 hindsight phases
    eps_all = []
    for k in ("SC100", "N100"):
        lab, eps = phase_labels(px[k], k)
        out[f"R1_phase_{k}"] = lab.reindex(g)
        eps_all += eps
        # Detail variant (also hindsight): the first 13 weeks after any 10%+ trough are
        # "rebound (13w after trough)"; the rest of the recovery stays "recovery (later)".
        tr = sorted(pd.Timestamp(e["trough"]) for e in eps)
        pos = pd.Series(np.arange(len(g)), index=g)
        last_tr = pd.Series([max([t for t in tr if t < d], default=pd.NaT) for d in g], index=g)
        since = pd.Series([pos[d] - pos[t] if pd.notna(t) else np.nan for d, t in last_tr.items()], index=g)
        det = out[f"R1_phase_{k}"].astype(object).copy()
        rec = det == "recovery"
        det[rec & (since <= 13)] = "rebound (13w after trough)"
        det[rec & ~(since <= 13)] = "recovery (later)"
        out[f"R1d_phase_{k}"] = det
    ep = pd.DataFrame(eps_all).sort_values(["index", "peak", "level"])

    # R2 trend
    ma = px["SC100"].rolling(40, min_periods=40).mean()
    out["SC100_ma40"] = ma
    out["R2_trend"] = np.where(ma.isna(), None, np.where(px["SC100"] > ma, "above 40w MA", "below 40w MA"))

    # R3 volatility terciles with expanding past-only thresholds
    lr = np.log(px["SC100"]).diff()
    v13 = lr.rolling(13, min_periods=13).std() * np.sqrt(52)
    past = v13.shift(1)
    q1 = past.expanding(min_periods=52).quantile(1 / 3)
    q2 = past.expanding(min_periods=52).quantile(2 / 3)
    out["SC100_vol13"] = v13
    out["vol_q33_past"] = q1
    out["vol_q67_past"] = q2
    r3 = np.where(v13 <= q1, "low vol", np.where(v13 <= q2, "mid vol", "high vol"))
    out["R3_vol"] = np.where(q1.isna() | v13.isna(), None, r3)

    # R4 leadership
    rel = px["SC100"].pct_change(26, fill_method=None) - px["N100"].pct_change(26, fill_method=None)
    out["SC_minus_N_26w"] = rel
    out["R4_lead"] = np.where(rel.isna(), None, np.where(rel > 0.05, "small-led", np.where(rel < -0.05, "large-led", "neutral")))

    # R5 signal state, R6 breadth
    s = sg.reindex(g)
    for c in ("N50", "N100", "MC100", "SC100"):
        out[f"sig_{c}"] = s[c]
    n1, s1 = s["N100"], s["SC100"]
    st = np.where(n1.isna() | s1.isna(), None,
                  np.where((n1 == 1) & (s1 == 1), "both BUY",
                           np.where(n1 == 1, "only N100 BUY", np.where(s1 == 1, "only SC100 BUY", "both SELL"))))
    out["R5_state"] = st
    br = s[["N50", "N100", "MC100", "SC100"]]
    out["R6_breadth"] = np.where(br.isna().any(axis=1), None, br.sum(axis=1).astype("Int64").astype(str) + " of 4 BUY")
    return out, ep


def main() -> None:
    out, ep = build()
    out.to_csv(DEEP / "regimes_weekly_labels.csv")
    ep.to_csv(DEEP / "regimes_phase_episodes.csv", index=False)
    w = out[(out.index >= "2007-07-01")]
    print(ep.to_string())
    for c in ["R1_phase_SC100", "R1_phase_N100", "R1d_phase_SC100", "R1d_phase_N100", "R2_trend", "R3_vol", "R4_lead", "R5_state", "R6_breadth"]:
        print(c, w[c].value_counts(dropna=False).to_dict())


if __name__ == "__main__":
    main()
