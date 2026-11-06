# -*- coding: utf-8 -*-
"""
Verification checks for the v2 study (plan items 2-8). Writes
`evidence/segment_v2/verification.json` and exits non-zero if any check fails.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import segment_v2 as V
import stats_v2 as S
from common import (AA_INDEX_CSV, EVIDENCE_DIR, PAIRS, PARENT_INDEX_CSV,
                    cagr_from_returns, load_index_levels)
from run_segment_v2 import load_inputs

OUT = V.EVIDENCE_SUBDIR


def main() -> None:
    inp = load_inputs()
    cal, eff, reviews, sim = inp["cal"], inp["eff"], inp["reviews"], inp["sim"]
    checks = {}

    # 3. Unit checks on 0044.
    aa, parent = "SCMO_0044", "SCMO_0010"
    ctx = V.parent_ctx(parent, inp["hold"][inp["hold"]["parent"] == parent], reviews, cal)
    tags = V.tag_table(ctx, inp["taggers"]["hybrid"])
    st = V.build_sleeve(ctx, eff, tags, "event", "micro_own")
    par = {s.review: s for s in V.build_parent(ctx, eff)}
    sig = eff.loc[ctx.reviews, V.EVENT_COLS]
    all_buy = [r for r in ctx.reviews if (sig.loc[r] == "BUY").all()]
    all_sell = [r for r in ctx.reviews if (sig.loc[r] == "SELL").all()]
    bad_buy = sum(1 for s in st if s.review in all_buy and (
        abs(s.sleeve) > 1e-12 or set(s.weights) != set(par[s.review].weights)
        or any(abs(s.weights[k] - par[s.review].weights[k]) > 1e-12 for k in s.weights)))
    bad_sell = sum(1 for s in st if s.review in all_sell and (s.weights or abs(s.sleeve - 1) > 1e-12))
    checks["all_buy_equals_parent"] = {"weeks": len(all_buy), "violations": bad_buy, "ok": bad_buy == 0}
    checks["all_sell_is_full_sleeve"] = {"weeks": len(all_sell), "violations": bad_sell,
                                         "ok": bad_sell == 0}
    ends = [float(sim.run(st, b)[0].iloc[-1]) for b in V.COST_BPS]
    checks["cost_monotonic"] = {"end_nav_by_bps": dict(zip(map(str, V.COST_BPS), ends)),
                                "ok": ends[0] >= ends[1] >= ends[2]}
    # Between events, targets must not change (only fillability can force a trade).
    prev, changed = None, 0
    for s in st:
        if prev is not None and not s.event and (s.weights != prev.weights or s.sleeve != prev.sleeve):
            changed += 1
        prev = s
    _, log = sim.run(st, V.PRIMARY_BPS)
    ev = {s.review for s in st if s.event}
    non_event_trades = int((~pd.to_datetime(log["review"]).isin(ev)).sum())
    checks["no_target_change_between_events"] = {"violations": changed, "ok": changed == 0,
                                                 "non_event_trades_from_fillability": non_event_trades}

    # 2 & 6. PIT and tagging.
    audit = json.loads((OUT / "audit.json").read_text(encoding="utf-8"))
    tg = pd.read_csv(OUT / "bucket_tags.csv", parse_dates=["review", "snapshot"])
    first_mem = pd.Timestamp("2026-04-09")
    after = tg[tg["review"] >= first_mem]
    before = tg[tg["review"] < first_mem]
    fut = int((tg["snapshot"] > tg["review"]).sum())
    checks["tag_source_by_regime"] = {
        "after_seam_sources": after["tag_source"].value_counts().to_dict(),
        "before_seam_sources": before["tag_source"].value_counts().to_dict(),
        "ok": set(after["tag_source"]) <= {"membership", "nonmember_rank", "manual", "unranked"}
              and set(before["tag_source"]) <= {"rank", "rank>900", "unranked", "manual"}}
    checks["no_future_snapshot"] = {"violations": fut, "ok": fut == 0}
    pit_ok = all(v["ctx"]["pit_signal_before_entry_ok"] == v["ctx"]["pit_basket_not_future_ok"]
                 for v in audit["per_book"].values())
    checks["pit_asserts"] = {"ok": pit_ok, "note": "per-row asserts raise on violation; counts in audit"}
    checks["microcap_fallback"] = {"reviews": audit["microcap_fallback_reviews"],
                                   "ok": audit["microcap_fallback_reviews"] == 15}

    # 7. Report ties out to its own evidence.
    nav = pd.read_csv(OUT / "nav_curves.csv", index_col=0, parse_dates=True)
    sc = pd.read_csv(OUT / "scorecard.csv")
    worst = 0.0
    for _, r in sc.iterrows():
        lv = nav[f"{r['aa']}|{r['strategy']}|{r['cost_bps']:g}"]
        worst = max(worst, abs(S.cagr(lv) - r["cagr"]), abs(S.drawdown(lv)["max_dd"] - r["max_dd"]))
    summ = pd.read_csv(OUT / "rebalance_summary.csv", parse_dates=["entry"])
    tie = []
    for a in PAIRS:
        x = summ[(summ["aa"] == a) & summ["traded"]].iloc[-1]
        lv = nav[f"{a}|sleeve|20.8"]
        tie.append(abs(x["nav"] / 1.0 - lv.loc[x["entry"]] * float(
            sim.run(V.build_sleeve(V.parent_ctx(PAIRS[a], inp["hold"][inp["hold"]["parent"] == PAIRS[a]],
                                                reviews, cal),
                                   eff, V.tag_table(V.parent_ctx(
                                       PAIRS[a], inp["hold"][inp["hold"]["parent"] == PAIRS[a]],
                                       reviews, cal), inp["taggers"]["hybrid"]),
                                   "event", "micro_own"), V.PRIMARY_BPS)[0].loc[inp["start"]])))
    checks["stats_tie_out"] = {"max_abs_diff": worst, "ok": worst < 1e-12}
    checks["rebalance_nav_tie_out"] = {"max_abs_diff": max(tie), "ok": max(tie) < 1e-9}

    # 8. Published series against Study 1, on Study 1's exact window.
    s1 = pd.read_csv(EVIDENCE_DIR / "main" / "scorecard.csv", dtype={"portfolio": str})
    par, aan = load_index_levels(PARENT_INDEX_CSV), load_index_levels(AA_INDEX_CSV)
    diffs = {}
    for a, p in PAIRS.items():
        for lab, lv in ((a[-4:], aan[a]), (p[-4:], par[p])):
            lv = lv.loc["2021-11-01":"2026-08-21"]
            row = s1[s1["portfolio"] == lab].iloc[0]
            # Study 1 annualises over the span of the *return* dates (first
            # return = the day after the base date); stats_v2 spans from the
            # base date. Compare on Study 1's own convention, and record the
            # convention gap separately.
            diffs[lab] = {"cagr": cagr_from_returns(lv.pct_change()) - row["cagr"],
                          "convention_gap_pp": (S.cagr(lv) - row["cagr"]) * 100,
                          "max_dd": S.drawdown(lv)["max_dd"] - row["max_drawdown"]}
    worst8 = max(max(abs(d["cagr"]), abs(d["max_dd"])) for d in diffs.values())
    checks["published_ties_to_study1"] = {"diffs": diffs, "max_abs_diff": worst8, "ok": worst8 < 1e-9}
    starts = nav.apply(lambda c: c.loc[c.first_valid_index()])
    checks["all_series_start_at_1"] = {"ok": bool(np.allclose(starts.to_numpy(), 1.0))}

    ok = all(c["ok"] for c in checks.values())
    (OUT / "verification.json").write_text(json.dumps({"all_ok": ok, **checks}, indent=2,
                                                      default=str), encoding="utf-8")
    for k, c in checks.items():
        print(f"  {'OK ' if c['ok'] else 'FAIL'} {k}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
