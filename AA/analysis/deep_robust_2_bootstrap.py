# -*- coding: utf-8 -*-
"""
2. Stationary block bootstrap (Politis & Romano 1994) of the out-of-sample
cash-sleeve daily returns, 2007-07-02 -> 2021-10-29.

For each equity leg, the daily returns of the pair rule and of the reference
rule (bh, sc100, own) are resampled JOINTLY with the same block indices, so
their correlation is kept. Blocks have geometric lengths with a mean of 26
weeks (converted to sessions with the sample's own sessions-per-week), wrap
circularly, 2,000 draws, seed 20260925.

Per draw:
  cagr_diff  = CAGR(pair path) - CAGR(reference path), both annualised over
               the sample's calendar years;
  arith_diff = mean(r_pair - r_ref) * sessions per year;
  dd_shallower = pair's max DD on the resampled path is shallower than the reference's.

Also: mean-block sensitivity (13 / 26 / 52 weeks) and, as extras, the
2014-07 -> 2021-10 50/50 sleeve (OOS) and 2021-11 -> 2026-08 (IN-SAMPLE, not
evidence).

Writes robust_bootstrap.csv and robust_bootstrap_draws.csv (primary runs only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import deep_robust_common as C

DRAWS = 2000


def sb_indices(n: int, mean_block: float, draws: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < p
    newv = rng.integers(0, n, (draws, n))
    for t in range(1, n):
        idx[:, t] = np.where(jump[:, t], newv[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def path_stats(r: np.ndarray, idx: np.ndarray, years: float):
    x = r[idx]                                    # draws x n
    lg = np.log1p(x).sum(axis=1)
    cg = np.exp(lg / years) - 1
    nav = np.cumprod(1 + x, axis=1)
    peak = np.maximum.accumulate(nav, axis=1)
    dd = (nav / peak - 1).min(axis=1)
    dd = np.minimum(dd, 0.0)
    return cg, dd, x.mean(axis=1)


def main():
    cal, sg, lv, gc = C.load()
    runs = [("OOS 2007-07 -> 2021-10, cash", C.FULL_START, C.OOS_END, "cash", True),
            ("OOS 2014-07 -> 2021-10, 50/50", C.GOLD_START, C.OOS_END, "5050", False),
            ("IN-SAMPLE 2021-11 -> 2026-08, 50/50 (not evidence)", C.IS_START, C.CUT, "5050", False),
            ("IN-SAMPLE 2021-11 -> 2026-08, cash (not evidence)", C.IS_START, C.CUT, "cash", False)]
    legs = ["SC100", "blend", "N100", "MC100", "N50"]
    rows, draws_out = [], {}
    for lab, a, b, sl, primary in runs:
        win = C.Window(cal, sg, lv, gc, a, b, sl)
        c = win.c
        n = len(c)
        years = (c[-1] - c[0]).days / 365.25
        spw = n / ((c[-1] - c[0]).days / 7)       # sessions per week
        spy = n / years
        rets = {}
        for leg in legs:
            for rn in ("pair", "bh", "sc100", "own"):
                if rn == "own" and leg == "blend":
                    continue
                nav = win.nav(C.rule_dec(sg, rn, leg), leg)
                r = nav.pct_change().fillna(0.0).to_numpy()
                rets[(leg, rn)] = r
        blocks = (13, 26, 52) if primary else (26,)
        for bw in blocks:
            rng = np.random.default_rng(C.SEED)
            mb = bw * spw
            idx = sb_indices(n, mb, DRAWS, rng)
            for leg in legs:
                cp, dp, mp = path_stats(rets[(leg, "pair")], idx, years)
                for ref in ("bh", "sc100", "own"):
                    if (leg, ref) not in rets or (leg == "SC100" and ref == "own"):
                        continue
                    cr, dr, mr = path_stats(rets[(leg, ref)], idx, years)
                    d = cp - cr
                    ad = (mp - mr) * spy
                    obs_p = float(np.exp(np.log1p(rets[(leg, "pair")]).sum() / years) - 1)
                    obs_r = float(np.exp(np.log1p(rets[(leg, ref)]).sum() / years) - 1)
                    obs_ad = float((rets[(leg, "pair")] - rets[(leg, ref)]).mean() * spy)
                    rows.append({"run": lab, "sleeve": sl, "mean_block_weeks": bw,
                                 "mean_block_sessions": round(mb, 1), "sessions": n, "years": round(years, 2),
                                 "leg": leg, "vs": ref, "draws": DRAWS,
                                 "obs_pair_cagr": obs_p, "obs_ref_cagr": obs_r, "obs_cagr_diff": obs_p - obs_r,
                                 "boot_median_cagr_diff": float(np.median(d)),
                                 "ci90_lo": float(np.percentile(d, 5)), "ci90_hi": float(np.percentile(d, 95)),
                                 "ci95_lo": float(np.percentile(d, 2.5)), "ci95_hi": float(np.percentile(d, 97.5)),
                                 "p_diff_gt_0": float((d > 0).mean()),
                                 "obs_arith_diff": obs_ad,
                                 "arith_ci90_lo": float(np.percentile(ad, 5)), "arith_ci90_hi": float(np.percentile(ad, 95)),
                                 "arith_ci95_lo": float(np.percentile(ad, 2.5)), "arith_ci95_hi": float(np.percentile(ad, 97.5)),
                                 "arith_p_gt_0": float((ad > 0).mean()),
                                 "p_pair_dd_shallower": float((dp > dr).mean()),
                                 "boot_median_pair_dd": float(np.median(dp)), "boot_median_ref_dd": float(np.median(dr)),
                                 "boot_p5_pair_dd": float(np.percentile(dp, 5)), "boot_p5_ref_dd": float(np.percentile(dr, 5))})
                    if primary and bw == 26 and leg in ("SC100", "blend", "N100"):
                        draws_out[f"{leg}|pair-{ref}|cagr_diff"] = d
            print(lab, bw, "done", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(C.OUT / "robust_bootstrap.csv", index=False)
    pd.DataFrame(draws_out).to_csv(C.OUT / "robust_bootstrap_draws.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[out.mean_block_weeks == 26][["run", "leg", "vs", "obs_cagr_diff", "ci90_lo", "ci90_hi", "ci95_lo",
                                           "ci95_hi", "p_diff_gt_0", "p_pair_dd_shallower"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
