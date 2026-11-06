# -*- coding: utf-8 -*-
"""
Independent validation of the section 4 off-window numbers.

Section 4 is the one place in the study where a headline figure is
*reconstructed* rather than read from a published series. The parent, gold and
cash columns are asset returns, so they only need a source check. The **sleeve**
column is weights x instrument prices, assembled by us, and it is the number the
whole "gold, not timing" conclusion leans on. So it gets an external test.

Five checks, in increasing strictness:

  V1  Weight closure       - on every defensive session the sleeve legs must sum
                             to the total defensive weight. Catches a dropped or
                             double-counted instrument.
  V2  Rebuild from source  - recompute every section 4 cell from the raw weight
                             CSVs and raw ETF closes, bypassing panel_daily.csv
                             entirely. Catches panel-build errors.
  V3  External ground truth- on fully-defensive sessions the AA's own PUBLISHED
                             NAV return must equal our reconstructed sleeve
                             return, because on those days the book *is* the
                             sleeve. This is the only check that uses data we did
                             not build, so it is the one that matters. Reported
                             twice: over all fully-defensive sessions, and over
                             "interior" ones excluding +/-3 days around any state
                             change, because the switch days are execution effects
                             (the AA fills intraday, we mark at close) and they
                             dominate the raw figure.
  V4  Episode additivity   - the per-episode sleeve returns in the episode ledger
                             must compound to the section 4 total.
  V5  Hand check           - one episode, printed session by session at the head
                             and tail, so a human can tie out a few rows against
                             the raw workbook.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import prices
from common import (
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    STATE_WEIGHT_COLS,
    daily_state,
)

TOL_CELL = 5e-4      # 5 bps on a cumulative return: rebuild must be near-exact
TOL_CLOSURE = 1e-6
TOL_INTERIOR_DRIFT = 0.015   # 1.5%/yr against the published NAV, interior sessions

# The cash leg is the one real discrepancy this validator found. `sleeve_return`
# in build_panel.py prices every defensive instrument from raw closes, and
# LIQUIDBEES has a constant NAV (999.99 throughout) because it distributes its
# yield -- so the early sleeve is credited 0% on a third of its weight.
# `prices.cash_total_return` exists exactly to fix that and this code path does
# not use it. V2 therefore reports the gap rather than failing on it.
LIQ = {"LIQUIDBEES", "LIQUIDCASE"}


def cum(s: pd.Series) -> float:
    return float(np.expm1(np.log1p(s.fillna(0.0)).sum()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run

    panel = pd.read_csv(out / "panel_daily.csv", index_col=0, parse_dates=True)
    pub = pd.read_csv(out / "offwindow_economics.csv")
    pub["aa_label"] = pub["aa_label"].astype(str).str.zfill(4)
    pub = pub.set_index("aa_label")
    cal = panel.index

    etf = prices.defensive_prices().reindex(cal).ffill()
    gold = etf["GOLDBEES"].pct_change()
    cash = prices.cash_total_return(cal)

    rows, notes = [], []

    for aa_id, p_id in PAIRS.items():
        lbl = LABELS[aa_id]

        # ── V2: rebuild the state straight from the weight CSV ─────────────
        st = daily_state(aa_id, cal)
        w_reb = st["w_def"].fillna(0.0)
        off_reb = w_reb > 0
        w_panel = panel[f"wdef_{aa_id}"].fillna(0.0)
        off_panel = w_panel > 0
        state_match = bool((off_reb == off_panel).all())

        # ── V1: do the legs close? ─────────────────────────────────────────
        legs = st[["w_gold", "w_liquid", "w_bond"]].fillna(0.0).sum(axis=1)
        closure = float((legs[off_reb] - w_reb[off_reb]).abs().max())

        # per-instrument weights must also close to the leg totals
        inst = st[[c for c in STATE_WEIGHT_COLS if c.startswith("wi_")]].fillna(0.0)
        inst_closure = float((inst.sum(axis=1)[off_reb] - w_reb[off_reb]).abs().max())

        # ── V2 continued: rebuild the sleeve return from instruments ───────
        # rdef must equal sum over instruments of (weight_within_sleeve x return)
        rets = etf.pct_change()
        num = pd.Series(0.0, index=cal)
        for c in inst.columns:
            t = c[3:]
            r = cash if t in ("LIQUIDBEES", "LIQUIDCASE") else rets.get(t)
            if r is None:
                notes.append(f"{lbl}: no price series for {t}")
                continue
            num = num.add(inst[c] * r.fillna(0.0), fill_value=0.0)
        sleeve_tr = (num / w_reb.replace(0.0, np.nan)).fillna(0.0)

        # raw-price rebuild, i.e. exactly what build_panel does
        num_raw = pd.Series(0.0, index=cal)
        for c in inst.columns:
            t = c[3:]
            r = rets.get(t)
            if r is not None:
                num_raw = num_raw.add(inst[c] * r.fillna(0.0), fill_value=0.0)
        sleeve_raw = (num_raw / w_reb.replace(0.0, np.nan)).fillna(0.0)

        # ── V3: external ground truth on FULLY defensive sessions ─────────
        full = (w_reb > 0.999)
        r_aa_pub = panel[f"r_{aa_id}"]          # from indices.csv, not built by us
        chg = (w_reb != w_reb.shift())
        near = chg.rolling(7, center=True, min_periods=1).max().astype(bool)
        interior = full & ~near

        def drift(mask, series):
            n = int(mask.sum())
            if not n:
                return np.nan
            a, b = cum(r_aa_pub[mask]), cum(series[mask])
            return ((1 + b) / (1 + a)) ** (252.0 / n) - 1

        n_full = int(full.sum())
        aa_cum = cum(r_aa_pub[full])
        slv_cum = cum(sleeve_raw[full])
        drift_ann = drift(full, sleeve_raw)
        drift_interior = drift(interior, sleeve_raw)
        med_abs = float((sleeve_raw[full] - r_aa_pub[full]).abs().median())

        rows.append({
            "aa": lbl,
            "V1_leg_closure_max_err": closure,
            "V1_instrument_closure_max_err": inst_closure,
            "V2_state_matches_panel": state_match,
            "V2_off_sessions_rebuilt": int(off_reb.sum()),
            "V2_off_sessions_published": int(pub.loc[lbl, "off_sessions"]),
            "V2_parent_err": cum(panel[f"r_{p_id}"][off_reb]) - pub.loc[lbl, "parent_return_while_out"],
            "V2_sleeve_err_rawpx": cum(sleeve_raw[off_reb]) - pub.loc[lbl, "actual_sleeve_return_while_out"],
            "V2_sleeve_cash_yield_gap": cum(sleeve_tr[off_reb]) - cum(sleeve_raw[off_reb]),
            "V2_gold_err": cum(gold[off_reb]) - pub.loc[lbl, "gold_return_while_out"],
            "V2_cash_err": cum(cash[off_reb]) - pub.loc[lbl, "cash_return_while_out"],
            "V3_fully_defensive_sessions": n_full,
            "V3_published_AA_cum": aa_cum,
            "V3_our_sleeve_cum": slv_cum,
            "V3_drift_ann_all_full": drift_ann,
            "V3_sessions_interior": int(interior.sum()),
            "V3_drift_ann_interior": drift_interior,
            "V3_median_abs_daily_diff_bps": med_abs * 1e4,
        })

    res = pd.DataFrame(rows)

    # ── V4: episode ledger must compound to the section 4 total ───────────
    ep = pd.read_csv(out / "episode_ledger.csv")
    ep["aa_label"] = ep["aa_label"].astype(str).str.zfill(4)
    v4 = []
    for lbl, g in ep.groupby("aa_label"):
        prod = float(np.prod(1.0 + g["sleeve_return"].to_numpy()) - 1.0)
        v4.append({"aa": lbl, "episodes": len(g),
                   "episodes_compounded": prod,
                   "section4_sleeve": pub.loc[lbl, "actual_sleeve_return_while_out"],
                   "diff": prod - pub.loc[lbl, "actual_sleeve_return_while_out"]})
    v4 = pd.DataFrame(v4)

    pd.set_option("display.width", 250)
    print("=== V1/V2: weight closure and rebuild-from-source ===")
    print(res[["aa", "V1_leg_closure_max_err", "V1_instrument_closure_max_err",
               "V2_state_matches_panel", "V2_off_sessions_rebuilt",
               "V2_off_sessions_published", "V2_parent_err", "V2_sleeve_err_rawpx",
               "V2_gold_err", "V2_cash_err"]].to_string(index=False))
    print()
    print("  FINDING: the sleeve column credits the LIQUIDBEES leg 0% yield "
          "(constant NAV, distributes).")
    print("  Cumulative understatement if cash_total_return were used instead:")
    for _, r in res.iterrows():
        print(f"    {r['aa']}  {r['V2_sleeve_cash_yield_gap']*100:+.3f} pp")

    print("\n=== V3: EXTERNAL check - published AA NAV vs our sleeve, "
          "fully-defensive sessions only ===")
    v3 = res[["aa", "V3_fully_defensive_sessions", "V3_published_AA_cum",
              "V3_our_sleeve_cum", "V3_drift_ann_all_full", "V3_sessions_interior",
              "V3_drift_ann_interior", "V3_median_abs_daily_diff_bps"]].copy()
    for c in ("V3_published_AA_cum", "V3_our_sleeve_cum", "V3_drift_ann_all_full",
              "V3_drift_ann_interior"):
        v3[c] = (v3[c] * 100).round(3)
    print(v3.round(3).to_string(index=False))

    print("\n=== V4: episode ledger compounds to the section 4 sleeve total ===")
    print(v4.round(6).to_string(index=False))

    if notes:
        print("\nNOTES:")
        for n in notes:
            print("  " + n)

    # ── V5: hand-checkable rows ───────────────────────────────────────────
    aa_id = "SCMO_0042"
    st = daily_state(aa_id, cal)
    w = st["w_def"].fillna(0.0)
    off = w > 0
    grp = (off != off.shift()).cumsum()
    seg = [g for _, g in off.groupby(grp) if g.iloc[0]][3]   # episode 4, 27 sessions
    print(f"\n=== V5: 0042 episode 4 ({seg.index.min().date()} -> "
          f"{seg.index.max().date()}, {len(seg)} sessions), hand-checkable ===")
    # Show the instruments ACTUALLY held on these dates, not a fixed pair -- the
    # sleeve switched from the Nippon BeES pair to the Zerodha pair in Oct-2024,
    # so displaying GOLDBEES here would not tie out against r_sleeve.
    wi = st[[c for c in STATE_WEIGHT_COLS if c.startswith("wi_")]].loc[seg.index]
    held = [c[3:] for c in wi.columns if (wi[c].fillna(0.0) > 0).any()]
    print(f"    instruments held: {', '.join(held)}")
    cols = {
        "w_def": st["w_def"].loc[seg.index].round(4),
    }
    for t in held:
        cols[f"w_{t}"] = st[f"wi_{t}"].loc[seg.index].round(4)
        cols[f"{t}_close"] = etf[t].loc[seg.index].round(3)
        cols[f"r_{t}_%"] = (etf[t].pct_change().loc[seg.index] * 100).round(4)
    cols["r_sleeve_%"] = (panel[f"rdef_{aa_id}"].loc[seg.index] * 100).round(4)
    cols["check_%"] = sum(
        st[f"wi_{t}"].loc[seg.index] * etf[t].pct_change().loc[seg.index]
        for t in held
    ).div(st["w_def"].loc[seg.index]).mul(100).round(4)
    tb = pd.DataFrame(cols)
    print(pd.concat([tb.head(4), tb.tail(3)]).to_string())
    print(f"  episode sleeve return, compounded: "
          f"{cum(panel[f'rdef_{aa_id}'].loc[seg.index])*100:+.4f}%")

    res.to_csv(out / "validate_section4.csv", index=False)
    v4.to_csv(out / "validate_section4_episodes.csv", index=False)

    # gates
    bad = []
    if res["V1_leg_closure_max_err"].max() > TOL_CLOSURE:
        bad.append("V1 leg closure")
    if res["V1_instrument_closure_max_err"].max() > TOL_CLOSURE:
        bad.append("V1 instrument closure")
    if not res["V2_state_matches_panel"].all():
        bad.append("V2 state mismatch")
    for c in ("V2_parent_err", "V2_sleeve_err_rawpx", "V2_gold_err", "V2_cash_err"):
        if res[c].abs().max() > TOL_CELL:
            bad.append(c)
    if v4["diff"].abs().max() > TOL_CELL:
        bad.append("V4 episode additivity")
    if res["V3_drift_ann_interior"].abs().max() > TOL_INTERIOR_DRIFT:
        bad.append("V3 interior drift vs published NAV")
    print("\n" + ("VALIDATION PASSED" if not bad else "FAILED: " + ", ".join(bad)))


if __name__ == "__main__":
    main()
