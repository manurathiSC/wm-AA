# -*- coding: utf-8 -*-
"""
4. Execution delay and trading cost.

Delay: every weekly decision acts 0 / 1 / 2 / 4 reviews later than it would
(on top of the base next-session fill). Cost: 0 / 20.8 / 50 / 100 bps per full
switch. Pair, SC100-only, own and bh on SC100, the blend and N100.

Primary: out of sample 2007-07-02 -> 2021-10-29, cash sleeve. Extras: OOS
2014-07 -> 2021-10 with 50/50, and 2021-11 -> 2026-08 IN-SAMPLE (not evidence).

Also the break-even cost per switch at which the pair's CAGR falls to bh's
(delay 0), and the CAGR cost of each extra 10 bps.

Writes robust_delay_cost.csv and robust_breakeven_cost.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import deep_robust_common as C

LEGS = ["SC100", "blend", "N100"]
DELAYS = [0, 1, 2, 4]
COSTS = [0.0, 20.8, 50.0, 100.0]


def main():
    cal, sg, lv, gc = C.load()
    periods = [("OOS 2007-21, cash", C.FULL_START, C.OOS_END, "cash"),
               ("OOS 2014-21, 50/50", C.GOLD_START, C.OOS_END, "5050"),
               ("IN-SAMPLE 2021-26, 50/50 (not evidence)", C.IS_START, C.CUT, "5050"),
               ("IN-SAMPLE 2021-26, cash (not evidence)", C.IS_START, C.CUT, "cash")]
    rows, be = [], []
    for lab, a, b, sl in periods:
        win = C.Window(cal, sg, lv, gc, a, b, sl, legs=LEGS)
        for leg in LEGS:
            bh_nav = win.nav(C.rule_dec(sg, "bh"), leg)
            bh = C.stats(bh_nav)
            for rn in ("pair", "sc100", "own"):
                if rn == "own" and leg == "blend":
                    continue
                if rn == "own" and leg == "SC100":
                    continue  # identical to sc100
                base = C.rule_dec(sg, rn, leg)
                for lag in DELAYS:
                    dec = base.shift(lag)
                    for cost in COSTS:
                        nav, w = win.nav_w(dec, leg, cost)
                        d = dec.loc[(dec.index >= win.a - pd.Timedelta(days=7)) & (dec.index <= win.b)]
                        s = C.stats(nav, w, d)
                        rows.append({"period": lab, "sleeve": sl, "leg": leg, "rule": rn, "delay_weeks": lag,
                                     "cost_bps": cost, **s, "bh_cagr": bh["cagr"], "bh_max_dd_daily": bh["max_dd_daily"],
                                     "bh_max_dd_friday": bh["max_dd_friday"], "minus_bh_cagr": s["cagr"] - bh["cagr"]})
                # break-even cost vs bh at delay 0
                f = lambda c_: C.cagr(win.nav(base, leg, c_)) - bh["cagr"]
                f0 = f(0.0)
                # bracket up to 1,000 bps (10% per switch) so the NAV stays positive
                bec = brentq(f, 0.0, 1000.0) if f0 > 0 and f(1000.0) < 0 else (np.nan if f0 <= 0 else np.inf)
                slope = (C.cagr(win.nav(base, leg, 30.8)) - C.cagr(win.nav(base, leg, 20.8)))
                be.append({"period": lab, "leg": leg, "rule": rn, "cagr_at_0bps": C.cagr(win.nav(base, leg, 0.0)),
                           "bh_cagr": bh["cagr"], "breakeven_cost_bps_vs_bh": bec,
                           "cagr_change_per_extra_10bps": slope,
                           "note": "rule below bh even at 0 bps" if f0 <= 0 else ""})
        print(lab, "done", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(C.OUT / "robust_delay_cost.csv", index=False)
    pd.DataFrame(be).to_csv(C.OUT / "robust_breakeven_cost.csv", index=False)
    pd.set_option("display.width", 250)
    x = out[(out.period == "OOS 2007-21, cash") & (out.rule.isin(["pair", "sc100"]))]
    print(x.pivot_table(index=["leg", "rule", "delay_weeks"], columns="cost_bps", values="cagr").round(4))
    print(x.pivot_table(index=["leg", "rule", "delay_weeks"], columns="cost_bps", values="max_dd_daily").round(3))
    print(pd.DataFrame(be).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
