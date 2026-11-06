# -*- coding: utf-8 -*-
"""
Build `evidence/why_n100sc100/report.html` from the outputs of
`why_n100sc100.py` and `why_parents_oos.py`. Same house style as the Study 1
and segment-v2 reports.
"""

from __future__ import annotations

import datetime
import json
import math

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR, PAIRS
from why_n100sc100 import calendar, index_closes

E = EVIDENCE_DIR / "why_n100sc100"
SEG = EVIDENCE_DIR / "segment_v2"


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if (math.isnan(x) or math.isinf(x)) else float(f"{x:.6g}")
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, datetime.date)):
        return x.strftime("%Y-%m-%d")
    return x


def recs(df):
    return [clean(r) for r in df.to_dict(orient="records")]


def weekly(df: pd.DataFrame) -> dict:
    w = df.resample("W-FRI").last().dropna(how="all")
    return {"dates": [d.strftime("%Y-%m-%d") for d in w.index],
            "series": {c: [None if pd.isna(v) else round(float(v), 4) for v in w[c]] for c in w.columns}}


def yearly(n):
    n = n.dropna()
    ye = n.groupby(n.index.year).last()
    return ye / pd.concat([pd.Series([n.iloc[0]], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:] - 1


def main() -> None:
    books = list(PAIRS)
    # in-sample attribution
    att = pd.read_csv(E / "attribution_in_sample.csv")
    stt = pd.read_csv(E / "disagreement_stretches.csv")
    x = stt[(stt["a"] == "n100_and_sc100") & (stt["b"] == "sc100_only")]
    stretches = (x.groupby(["from", "to", "a_in_equity"])
                 .agg(sessions=("sessions", "first"), parent=("parent_return", "mean"),
                      sleeve=("sleeve_return", "first"), gold=("gold_return", "first"),
                      contrib=("log_contrib", "mean")).reset_index())
    # states
    s_is = pd.read_csv(E / "states_in_sample_summary.csv")
    s_oos = pd.read_csv(E / "states_oos_summary.csv")
    # unconfirmed-rally stretches out of sample, with what small caps did
    cal = calendar()
    idx = index_closes(cal)
    st = pd.read_csv(E / "states_oos.csv", parse_dates=["review"])
    u = st[st["state"] == "only SC100 BUY"].copy()
    u["blk"] = (u["review"].diff() > pd.Timedelta(days=8)).cumsum()
    urows = []
    for _, g in u.groupby("blk"):
        a = cal[cal.searchsorted(g["review"].min(), side="right")]
        b = cal[min(cal.searchsorted(g["review"].max(), side="right") + 5, len(cal) - 1)]
        urows.append({"start": g["review"].min().date(), "end": g["review"].max().date(),
                      "weeks": len(g), "sc100": float(idx["SC100"][b] / idx["SC100"][a] - 1),
                      "n100": float(idx["N100"][b] / idx["N100"][a] - 1)})
    # anatomy
    an = pd.read_csv(E / "switch_anatomy.csv")
    # index backtests
    ib = pd.read_csv(E / "index_backtests.csv")
    c_cash = pd.read_csv(E / "index_curves_oos_cash.csv", index_col=0, parse_dates=True)
    keep = [c for c in c_cash.columns if c.split("|")[1] in ("buy_hold", "SC100 only", "N100 only", "N100 AND SC100")]
    # parents OOS
    po = pd.read_csv(E / "parents_oos_results.csv")
    pc = pd.read_csv(E / "parents_oos_curves.csv", index_col=0, parse_dates=True)
    pcov = pd.read_csv(E / "parents_oos_coverage.csv")
    pkeep = [c for c in pc.columns if c.endswith("|gold+cash") or c.split("|")[1] == "parent"]
    # yearly tables
    yr_par = {}
    for rule in ["parent", "SC100 only", "N100 AND SC100", "current rule*", "segment rule*"]:
        cols = [f"{a}|{rule}|gold+cash" for a in books]
        yr_par[rule] = pd.concat([yearly(pc[c]) for c in cols], axis=1).mean(axis=1)
    yr_idx = pd.read_csv(E / "oos_yearly_blend_cash.csv").pivot(index="rule", columns="year", values="return")
    nav = pd.read_csv(SEG / "nav_curves.csv", index_col=0, parse_dates=True)
    yr_is = {}
    for rule, lab in [("parent|0", "parent"), ("sc100_only|20.8", "SC100 only"),
                      ("n100_and_sc100|20.8", "N100 AND SC100"), ("production_v2|20.8", "current rule"),
                      ("sleeve|20.8", "segment rule")]:
        yr_is[lab] = pd.concat([yearly(nav[f"{a}|{rule}"]) for a in books], axis=1).mean(axis=1)
    # in-sample book-level summary for the three rules
    sc = pd.read_csv(SEG / "scorecard.csv")
    isb = sc[(sc["cost_bps"] == 20.8) & sc["strategy"].isin(
        ["n100_and_sc100", "sc100_only", "production_v2", "sleeve", "parent"])][
        ["aa", "strategy", "cagr", "max_dd", "sharpe", "avg_equity_weight", "trades"]]
    rob = pd.read_csv(E / "robustness_in_sample.csv")
    # gold inside the sleeve
    gs = pd.read_csv(E / "gold_sleeve_results.csv")
    gs = gs[gs["rule"] != "parent"]
    gsum = []
    gcur = pd.concat([pd.read_csv(E / "gold_sleeve_curves_is.csv", index_col=0, parse_dates=True),
                      pd.read_csv(E / "gold_sleeve_curves_oos.csv", index_col=0, parse_dates=True)], axis=1)
    sub = {"2014–18 (gold flat)": ("2014-07-07", "2018-12-31"), "2019–21 (gold rising)": ("2019-01-01", "2021-10-29")}

    def fri_dd(per, lab, aa, rule, sleeve):
        # Worst fall on Friday closes, the marks the weekly signals see.
        s_ = gcur[f"{per}|{aa}|{rule}|{sleeve}"].dropna()
        if lab in sub:
            s_ = s_.loc[sub[lab][0]:sub[lab][1]]
        w_ = s_.resample("W-FRI").last().dropna()
        return float((w_ / w_.cummax() - 1).min())

    for per, lab, cf, df in [("in-sample 2021-26", "in-sample 2021–26", "cagr", "max_dd"),
                             ("out-of-sample 2014-21", "out of sample 2014–21", "cagr", "max_dd"),
                             ("out-of-sample 2014-21", "2014–18 (gold flat)", "cagr_2014_18", "max_dd_2014_18"),
                             ("out-of-sample 2014-21", "2019–21 (gold rising)", "cagr_2019_21", "max_dd_2019_21")]:
        x = gs[gs["period"] == per].groupby(["rule", "sleeve"])[[cf, df]].mean().reset_index()
        for _, r in x.iterrows():
            ddw = np.mean([fri_dd(per, lab, a, r["rule"], r["sleeve"]) for a in PAIRS])
            gsum.append({"period": lab, "rule": r["rule"], "sleeve": r["sleeve"], "cagr": r[cf], "max_dd": r[df],
                         "max_dd_friday": ddw})
    gshare = (gs[gs["sleeve"] == "gold trend 100%"].groupby(["period", "rule"])["avg_gold_share_when_defensive"]
              .mean().reset_index())
    gold_it = pd.read_csv(E / "gold_sleeve_gold_itself.csv")
    gw = pd.read_csv(E / "gold_signal_weekly.csv", parse_dates=["week_end"])
    from why_n100sc100 import gold_cash
    gl = gold_cash(calendar())["gold"].dropna()
    gl = gl.loc[:"2026-08-21"]
    # Daily closes, so one-day moves such as 2026-01-29 / 2026-03-23 show; the
    # weekly signal is carried forward from its week-end session.
    sigw = gw.set_index("week_end")["gold_signal"]
    sigw = sigw[~sigw.index.duplicated(keep="last")]
    sigw = sigw.reindex(gl.index.union(sigw.index)).ffill().reindex(gl.index)
    bounds = {"2014-07 -> 2018-12": ("2014-07-07", "2018-12-31"), "2019-01 -> 2021-10": ("2019-01-01", "2021-10-29"),
              "2021-11 -> 2026-08": ("2021-11-03", "2026-08-21")}
    fri = []
    for per_ in gold_it["period"]:
        w_ = gl.loc[bounds[per_][0]:bounds[per_][1]].resample("W-FRI").last().dropna()
        fri.append(float((w_ / w_.cummax() - 1).min()))
    gold_it["gold_max_dd_friday"] = fri
    tri_p = pd.read_csv(E / "triple_portfolio_results.csv")
    tri_i = pd.read_csv(E / "triple_index_results.csv")
    tri_m = pd.read_csv(E / "triple_marginal_summary.csv")
    tri_s = pd.read_csv(E / "triple_marginal_stretches.csv")
    tc = pd.read_csv(E / "triple_index_curves.csv", index_col=0, parse_dates=True)
    tc = tc[[c for c in tc.columns if c.startswith("2007-26 full, cash|")]]
    tc.columns = [c.split("|", 1)[1] for c in tc.columns]
    tri_curves = weekly(tc)
    gold_chart = {"dates": [d.strftime("%Y-%m-%d") for d in gl.index],
                  "level": [round(float(v) / float(gl.iloc[0]), 4) for v in gl],
                  "signal": [None if pd.isna(v) else int(v) for v in sigw]}

    payload = clean({
        "attribution": recs(att), "stretches": recs(stretches),
        "states_is": recs(s_is), "states_oos": recs(s_oos), "unconfirmed": urows,
        "anatomy": recs(an), "index": recs(ib),
        "idx_curves": weekly(c_cash[keep]),
        "parents": recs(po), "parents_cov": recs(pcov), "par_curves": weekly(pc[pkeep]),
        "yr_par": {k: {str(y): v for y, v in s.items()} for k, s in yr_par.items()},
        "yr_idx": {k: {str(y): v for y, v in yr_idx.loc[k].items()} for k in yr_idx.index},
        "yr_is": {k: {str(y): v for y, v in s.items()} for k, s in yr_is.items()},
        "is_books": recs(isb), "rob": recs(rob),
        "gold_sum": gsum, "gold_share": recs(gshare), "gold_itself": recs(gold_it), "gold_chart": gold_chart,
        "tri_p": recs(tri_p), "tri_i": recs(tri_i), "tri_m": recs(tri_m), "tri_s": recs(tri_s), "tri_curves": tri_curves,
    })
    html = (E.parent.parent / "why_report_template.html").read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(payload, separators=(",", ":"), allow_nan=False))
    (E / "report.html").write_text(html, encoding="utf-8")
    print(f"wrote {E / 'report.html'} ({(E / 'report.html').stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
