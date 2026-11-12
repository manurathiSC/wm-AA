"""T10 Step 1: counts only (no price, NAV or return is read): how the weekly FS score behaves against the three-index switch.

    python -I tests/T10/step1_counts.py       writes tests/T10/logs/step_1_counts.json and prints a table

Reads only APPROVED rows of data/APPROVED_DATA.md (checked in code): D17 extended published NAVs (calendar), D03 extended Master files
(signals), D19 weight matrices + sources + columns (baskets), D20-D23 tags (through analysis/tag_lookup.py).
Decision dates as T03 section 3 / T06 / T07: T0, then the last D17 session of every later ISO week; the signal of an index = the latest Master
row on or before the date. Basket in effect = the latest non-skipped basket with rebalance_date <= the date. Tags are read AT EVERY decision
date (T10; T07 read them only at events).
Band -> signal: Large -> Nifty 100, Mid -> Midcap 100, Small and below -> Smallcap 100.
FS = (number of held stocks whose band's index is BUY) / n, decided in integers: IN iff 5k >= 3n (FS >= 0.60 exactly).
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "data"))
sys.path.insert(0, str(AA / "analysis"))
import check_approved_data as CA  # noqa: E402
from tag_lookup import TagLookup  # noqa: E402

BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
LIVE_START = pd.Timestamp("2021-11-01")
END = pd.Timestamp("2026-10-30")          # D03 (signals) ends here; the window cannot end later
APPROVED = {r["file"] for r in CA.rows() if r["status"] == "APPROVED"}
BANDS = ["Large", "Mid", "Small and below"]
THRESHOLDS = [Fraction(2, 5), Fraction(1, 2), Fraction(3, 5), Fraction(7, 10), Fraction(4, 5)]


def need(rel: str) -> Path:
    assert rel in APPROVED, f"not an APPROVED row of data/APPROVED_DATA.md: {rel}"
    return AA / rel


def runs(flags):
    out, c = [], 0
    for f in flags:
        if f:
            c += 1
        elif c:
            out.append(c); c = 0
    if c:
        out.append(c)
    return out


def float_fs(counts, signals, n, order):
    """Production's float arithmetic: sum over buckets of share * (1.0 if BUY else 0.0), buckets in the given order."""
    fs = 0.0
    for b in order:
        if counts[b] == 0:
            continue
        fs += (counts[b] / n) * (1.0 if signals[b] == 1 else 0.0)
    return fs


def main():
    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(need(f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx"), parse_dates=["Date"])
        sig[n] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    assert all(s.index.max() >= END for s in sig.values()), "a signal file ends before the window end"

    tl = TagLookup.from_files(need("Historical Data/extended_2026-11-12/tags/mcap_rank_panel.csv"),
                              need("Historical Data/extended_2026-11-12/tags/membership_panel.csv"),
                              need("Historical Data/extended_2026-11-12/symbology/symbology_changes.csv"))
    out = {"window_end": str(END.date()), "cutoff": str(tl.cutoff.date()), "books": {}}
    rows_print = []
    for b in BOOKS:
        raw = pd.read_csv(need(f"Historical Data/extended_2026-11-06/published_nav/{b}.csv"))
        cal = pd.DatetimeIndex(sorted(pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")))
        cal = cal[cal <= END]
        wm = pd.read_csv(need(f"data/holdings_matrix/{b}_holding_weight_matrix.csv"), parse_dates=["rebalance_date"]).set_index("rebalance_date")
        src = pd.read_csv(need(f"data/holdings_matrix/{b}_holding_weight_sources.csv"), parse_dates=["rebalance_date"])
        skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
        wm = wm[~wm.index.isin(skipped)].sort_index()
        colmap = pd.read_csv(need(f"data/holdings_matrix/{b}_columns.csv")).set_index("stock")["ISIN"].to_dict()
        res = {"calendar_first": str(cal[0].date()), "calendar_last": str(cal[-1].date()), "skipped_baskets_dropped": len(skipped)}
        for win, start in (("full", None), ("live", LIVE_START)):
            c = cal if start is None else cal[cal >= start]
            wk = pd.Series(c, index=c)
            iso = c.isocalendar()
            last = sorted(wk.groupby([iso.year.values, iso.week.values]).max().values)
            dates = [c[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > c[0]]
            st, basket, ks, ns, srcs, wfs, tie_diff, ties = [], [], [], [], [], [], [], []
            for d in dates:
                st.append(tuple(int(s.iloc[s.index.searchsorted(d, side="right") - 1] == "BUY") for s in sig.values()))
                i = wm.index.searchsorted(d, side="right") - 1
                assert i >= 0, f"no basket on {d.date()}"
                row = wm.iloc[i]
                held = row[row > 0]
                w = (held / held.sum()).values
                tags = [tl.tag(colmap[s], d) for s in held.index]
                bands = [t["band"] for t in tags]
                srcs += [t["source"] for t in tags]
                sigmap = {BANDS[j]: st[-1][j] for j in range(3)}
                counts = {bd: sum(1 for x in bands if x == bd) for bd in BANDS}
                n = len(bands)
                k = sum(counts[bd] for bd in BANDS if sigmap[bd] == 1)
                ks.append(k); ns.append(n)
                wfs.append(float(sum(wi for wi, bi in zip(w, bands) if sigmap[bi] == 1)))
                exact_in = 5 * k >= 3 * n
                f1 = float_fs(counts, sigmap, n, BANDS) >= 0.60
                f2 = float_fs(counts, sigmap, n, BANDS[::-1]) >= 0.60
                ties.append(5 * k == 3 * n)
                tie_diff.append((f1 != exact_in) or (f2 != exact_in))
                basket.append(wm.index[i])
            nw = len(dates)
            ks_a, ns_a = np.array(ks), np.array(ns)
            rule_in = [5 * k >= 3 * n for k, n in zip(ks, ns)]
            switch_in = [s == (1, 1, 1) for s in st]
            all_sell = [s == (0, 0, 0) for s in st]
            viol = sum(1 for r, s in zip(rule_in, switch_in) if s and not r)
            extra = [r and not s for r, s in zip(rule_in, switch_in)]          # rule IN, switch OUT
            thr = {}
            for t in THRESHOLDS:
                thr[str(t)] = int(sum(1 for k, n in zip(ks, ns) if Fraction(k, n) >= t))
            wfs_in = int(sum(1 for x in wfs if x >= 0.60 - 1e-12))
            flips_rule = [j for j in range(1, nw) if rule_in[j] != rule_in[j - 1]]
            flips_rule_same_signals = [j for j in flips_rule if st[j] == st[j - 1]]     # decision changed with no signal flip (a tag or basket change)
            flips_switch = [j for j in range(1, nw) if switch_in[j] != switch_in[j - 1]]
            bask = [j for j in range(1, nw) if basket[j] != basket[j - 1]]
            # an event: the decision changes, or a basket changes while the book is IN (the trade is on the next session, so the state read is week j's)
            ev_rule = sorted(set([0] + flips_rule + [j for j in bask if rule_in[j]]))
            ev_switch = sorted(set([0] + flips_switch + [j for j in bask if switch_in[j]]))
            fs_vals = (ks_a / ns_a)
            rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "weeks": nw,
                   "rule_IN_weeks": int(sum(rule_in)), "switch_IN_weeks": int(sum(switch_in)), "all_SELL_weeks": int(sum(all_sell)),
                   "rule_OUT_while_switch_IN_weeks": int(viol),
                   "extra_IN_weeks_rule_in_switch_out": int(sum(extra)), "extra_IN_stretches": len(runs(extra)), "extra_IN_stretch_lengths": runs(extra),
                   "rule_IN_weeks_by_signal_pattern": {"".join("B" if x else "S" for x in s): int(sum(1 for r, t in zip(rule_in, st) if r and t == s)) for s in sorted(set(st), reverse=True)},
                   "weeks_by_signal_pattern": {"".join("B" if x else "S" for x in s): int(sum(1 for t in st if t == s)) for s in sorted(set(st), reverse=True)},
                   "weeks_partial_FS_strictly_between_0_and_1": int(sum(1 for f in fs_vals if 0 < f < 1)),
                   "n_held_min_median_max": [int(ns_a.min()), float(np.median(ns_a)), int(ns_a.max())],
                   "FS_mean": float(fs_vals.mean()),
                   "exact_tie_weeks_FS_eq_0.60": int(sum(ties)), "tie_weeks_float_vs_exact_differ": int(sum(tie_diff)),
                   "rule_decision_flips": len(flips_rule), "rule_flips_with_no_signal_flip": len(flips_rule_same_signals),
                   "switch_decision_flips": len(flips_switch), "basket_changes": len(bask),
                   "events_rule_upper_bound": len(ev_rule), "events_switch_upper_bound": len(ev_switch),
                   "threshold_IN_weeks_count_weighted": thr,
                   "weight_weighted_FS_IN_weeks": wfs_in, "weight_vs_count_decision_differs_weeks": int(sum(1 for r, x in zip(rule_in, wfs) if r != (x >= 0.60 - 1e-12))),
                   "tag_source_holding_weeks": {k: int(v) for k, v in pd.Series(srcs).value_counts().items()}}
            res[win] = rec
            rows_print.append((b, win, rec))
        out["books"][b] = res
    p = Path(__file__).parent / "logs"
    p.mkdir(exist_ok=True)
    (p / "step_1_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"window end {END.date()}, tag cutoff {out['cutoff']}")
    for b, win, r in rows_print:
        print(f"{b} {win}: {r['start']} -> {r['end']}, {r['weeks']} weeks | rule IN {r['rule_IN_weeks']}, switch IN {r['switch_IN_weeks']}, all SELL {r['all_SELL_weeks']}, "
              f"rule OUT while switch IN {r['rule_OUT_while_switch_IN_weeks']} | extra IN weeks {r['extra_IN_weeks_rule_in_switch_out']} in {r['extra_IN_stretches']} stretches {r['extra_IN_stretch_lengths']}")
        print(f"      n held {r['n_held_min_median_max']}, mean FS {r['FS_mean']:.3f}, partial-FS weeks {r['weeks_partial_FS_strictly_between_0_and_1']} | exact ties {r['exact_tie_weeks_FS_eq_0.60']} "
              f"(float differs {r['tie_weeks_float_vs_exact_differ']}) | rule flips {r['rule_decision_flips']} (no signal flip {r['rule_flips_with_no_signal_flip']}), switch flips {r['switch_decision_flips']}, "
              f"basket changes {r['basket_changes']}, events <= {r['events_rule_upper_bound']} / {r['events_switch_upper_bound']}")
        print(f"      IN weeks by threshold {r['threshold_IN_weeks_count_weighted']} | weight-weighted FS IN {r['weight_weighted_FS_IN_weeks']} (differs from count in {r['weight_vs_count_decision_differs_weeks']}) | tag sources {r['tag_source_holding_weeks']}")
        print(f"      rule IN weeks by pattern {r['rule_IN_weeks_by_signal_pattern']} of {r['weeks_by_signal_pattern']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
