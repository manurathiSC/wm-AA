# -*- coding: utf-8 -*-
"""
Python replica of the workbook's daily check model (D_ sheets), and the
attribution of its gap to the harness by kind of day.

Each session: carry holdings from the previous close to today's fill price
(parent at its OHLC4 value, gold at OHLC4, cash at its level); if a review
executes today and the target changes, rebalance at the fill with 10.4 bps
one-way cost on the value traded; then carry holdings from the fill to the
close. Writes python_check_model_<book>_<period>.csv,
check_model_python_replica.csv and check_model_gap_attribution.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR, PAIRS

E = EVIDENCE_DIR / "final_strategy"
ONE_WAY = 20.8 / 2 / 1e4


def replica(df: pd.DataFrame, ex: dict) -> pd.Series:
    navs, tgt, prev = [], None, None
    Ec = Gc = Cc = 0.0
    for t, r in df.iterrows():
        if prev is None:
            Lf = Mf = Nf = 0.0
            O = 1.0
        else:
            Lf = Ec * r.parent_fill_nav / prev.parent_harness_nav
            Mf = Gc * r.gold_fill_ohlc4 / prev.gold_price
            Nf = Cc * r.cash_level / prev.cash_level
            O = Lf + Mf + Nf
        new = ex.get(t)
        if new is not None and (tgt is None or abs(new[0] - tgt[0]) > 1e-9 or abs(new[1] - tgt[1]) > 1e-9):
            tgt = new
            cost = (abs(O * tgt[0] - Lf) + abs(O * tgt[1] - Mf) + abs(O * tgt[2] - Nf)) * ONE_WAY
            Ra, Sa, Ta = (O - cost) * tgt[0], (O - cost) * tgt[1], (O - cost) * tgt[2]
        else:
            Ra, Sa, Ta = Lf, Mf, Nf
        Ec = Ra * r.parent_harness_nav / r.parent_fill_nav
        Gc = Sa * r.gold_price / r.gold_fill_ohlc4
        Cc = Ta
        navs.append(Ec + Gc + Cc)
        prev = r
    return pd.Series(navs, index=df.index)


def main():
    out, att = [], []
    for key, tag in (("live", "live"), ("1421", "2014_2021")):
        w = pd.read_csv(E / f"weekly_signals_{tag}.csv", parse_dates=["review", "entry_session"])
        ex = {r.entry_session: (r.equity_w, r.gold_w, r.cash_w) for r in w.itertuples()}
        for aa in PAIRS:
            df = pd.read_csv(E / f"daily_{aa}_{tag}.csv", index_col=0, parse_dates=True).loc[min(ex):]
            s = replica(df, ex)
            h = df.harness_nav
            s.rename("check_model_nav").to_frame().join(h).to_csv(E / f"python_check_model_{aa}_{tag}.csv")
            yrs = (s.index[-1] - s.index[0]).days / 365.25
            c1, c2 = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1, (h.iloc[-1] / h.iloc[0]) ** (1 / yrs) - 1
            out.append({"period": key, "aa": aa, "rows": len(s), "check_cagr": c1, "harness_cagr_same_rows": c2,
                        "gap_pp_yr": (c1 - c2) * 100, "check_maxdd": (s / s.cummax() - 1).min(), "harness_maxdd": (h / h.cummax() - 1).min(),
                        "final_check_nav": s.iloc[-1], "final_harness_nav": h.iloc[-1]})
            st = (df.gold_value + df.cash_value) / df.harness_nav > 0.5
            pv = st.shift().fillna(st.iloc[0])
            gap = (np.log(s).diff() - np.log(h).diff()).fillna(0)
            cat = np.select([st & pv, st & ~pv, ~st & pv, ~st & ~pv],
                            ["inside sleeve", "day moved into sleeve", "day moved back to equity", "inside equity"])
            g = gap.groupby(cat).sum() / yrs * 100
            att.append({"period": key, "aa": aa, "total": gap.sum() / yrs * 100,
                        **{k: float(g.get(k, 0.0)) for k in ("inside sleeve", "day moved into sleeve", "inside equity", "day moved back to equity")}})
    R = pd.DataFrame(out)
    R.to_csv(E / "check_model_python_replica.csv", index=False)
    A = pd.DataFrame(att)
    A.to_csv(E / "check_model_gap_attribution.csv", index=False)
    pd.set_option("display.width", 220)
    print(R.round(4).to_string(index=False))
    print(A.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
