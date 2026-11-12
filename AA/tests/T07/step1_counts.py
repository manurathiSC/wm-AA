"""T07 Step 1: counts only (no price, NAV or return is read): how often the three index signals disagree, how many events there are,
how the parents' weight splits across the three bands, and which tag source each holding-week uses.

    python -I tests/T07/step1_counts.py       writes tests/T07/logs/step_1_counts.json and prints a table

Reads only APPROVED rows of data/APPROVED_DATA.md (checked in code): D17 extended published NAVs (calendar), D03 extended Master files
(signals), D19 weight matrices + sources + columns (baskets), D20-D23 tags (through analysis/tag_lookup.py).
Decision dates as T03 section 3 / T06: T0, then the last D17 session of every later ISO week; the signal of an index = the latest Master
row on or before the date. Basket in effect = the latest non-skipped basket with rebalance_date <= the date.
Band -> signal: Large -> Nifty 100, Mid -> Midcap 100, Small and below -> Smallcap 100.
"""
import json
import sys
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
            st, basket, kept, shares, srcs = [], [], [], [], []
            for d in dates:
                st.append(tuple(int(s.iloc[s.index.searchsorted(d, side="right") - 1] == "BUY") for s in sig.values()))
                i = wm.index.searchsorted(d, side="right") - 1
                assert i >= 0, f"no basket on {d.date()}"
                row = wm.iloc[i]
                held = row[row > 0]
                w = held / held.sum()
                tags = [tl.tag(colmap[s], d) for s in held.index]
                bands = [t["band"] for t in tags]
                srcs += [t["source"] for t in tags]
                sh = {k: float(sum(wi for wi, bi in zip(w.values, bands) if bi == k)) for k in BANDS}
                shares.append(sh)
                kept.append(sum(sh[BANDS[j]] for j in range(3) if st[-1][j] == 1))
                basket.append(wm.index[i])
            n = len(dates)
            all_buy = [s == (1, 1, 1) for s in st]
            all_sell = [s == (0, 0, 0) for s in st]
            mixed = [not (a or z) for a, z in zip(all_buy, all_sell)]
            pat = {"".join("B" if x else "S" for x in s): int(sum(1 for t in st if t == s)) for s in sorted(set(st), reverse=True)}
            flips = {nm: int(sum(1 for k in range(1, n) if st[k][j] != st[k - 1][j])) for j, nm in enumerate(sig)}
            trig_flip = [k for k in range(1, n) if st[k] != st[k - 1]]
            trig_bask = [k for k in range(1, n) if basket[k] != basket[k - 1]]
            events = sorted(set([0] + trig_flip + trig_bask))
            mk = [kept[k] for k in range(n) if mixed[k]]
            rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "weeks": n,
                   "whole_book_IN_weeks": int(sum(all_buy)), "all_SELL_weeks": int(sum(all_sell)), "mixed_weeks": int(sum(mixed)),
                   "mixed_spells": len(runs(mixed)), "mixed_spell_lengths": runs(mixed),
                   "patterns_N100_MC100_SC100": pat, "flips_per_index": flips,
                   "events": len(events), "events_first": 1, "events_signal_flip": len(trig_flip), "events_basket_change": len(trig_bask),
                   "events_in_mixed_weeks": int(sum(1 for k in events if mixed[k])),
                   "mixed_weeks_with_partial_equity": int(sum(1 for x in mk if 0 < x < 1)),
                   "mean_kept_share_in_mixed_weeks": float(np.mean(mk)) if mk else None,
                   "mean_band_share_all_weeks": {k: float(np.mean([s[k] for s in shares])) for k in BANDS},
                   "mean_band_share_mixed_weeks": ({k: float(np.mean([s[k] for s, m in zip(shares, mixed) if m])) for k in BANDS} if sum(mixed) else None),
                   "tag_source_holding_weeks": {k: int(v) for k, v in pd.Series(srcs).value_counts().items()}}
            res[win] = rec
            rows_print.append((b, win, rec))
        out["books"][b] = res
    p = Path(__file__).parent / "logs"
    p.mkdir(exist_ok=True)
    (p / "step_1_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"window end {END.date()}, tag cutoff {out['cutoff']}")
    for b, win, r in rows_print:
        print(f"{b} {win}: {r['start']} -> {r['end']}, {r['weeks']} weeks | whole-book IN {r['whole_book_IN_weeks']}, all SELL {r['all_SELL_weeks']}, "
              f"mixed {r['mixed_weeks']} in {r['mixed_spells']} spells {r['mixed_spell_lengths']} | partial-equity mixed weeks {r['mixed_weeks_with_partial_equity']}, "
              f"mean kept share {r['mean_kept_share_in_mixed_weeks'] if r['mean_kept_share_in_mixed_weeks'] is None else round(r['mean_kept_share_in_mixed_weeks'], 3)} | "
              f"events {r['events']} (flip {r['events_signal_flip']}, basket {r['events_basket_change']}, in mixed weeks {r['events_in_mixed_weeks']}) | "
              f"flips {r['flips_per_index']} | patterns {r['patterns_N100_MC100_SC100']}")
        print(f"      band share all weeks {({k: round(v, 3) for k, v in r['mean_band_share_all_weeks'].items()})}; tag sources {r['tag_source_holding_weeks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
