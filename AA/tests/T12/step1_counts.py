"""T12 Step 1: counts only (no price, NAV or return is read). Fork of tests/T07/step1_counts.py on T11's window and calendar.

    python -I tests/T12/step1_counts.py      writes tests/T12/logs/step_1_counts.json and tests/T12/evidence/basket_tags_2014-09_2019-01.csv

Reads only APPROVED rows of data/APPROVED_DATA.md (checked in code): D26 NSE calendar, D03 Master files (signals), D19 weight matrices,
columns and sources, D05 rebalance history (skips, availableDate), D23b + D23 membership + D22 (tags, through analysis/tag_lookup.py).
Window: T0 = 2014-09-01 (the first basket effective on or after 2014-07-01, asserted equal for all four parents) .. END = 2019-01-02.
Decision dates: T0, then the last D26 session of every later ISO week. Signal of an index = its latest Master row dated on or before the
date (Smallcap 100 rows from 2011-11-25 only, rule 7). Basket in effect on d = the latest non-skipped basket with availableDate <= d.
Tags here are read at each decision date (counts) and, for the basket tag table, as of each basket's "relevant date": the D26 session
before the basket's first D26 session on or after its availableDate (T0's basket: T0 itself, as T07 section 3 step 4(i)).
The engine reads tags only at its events, as of the session before each event's trade session; these counts are upper bounds for it.
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
FIRST_PRICE = pd.Timestamp("2014-07-01")   # D18 and D09 start here
T0 = pd.Timestamp("2014-09-01")
END = pd.Timestamp("2019-01-02")
R2_START = pd.Timestamp("2015-01-02")
SC100_FROM = pd.Timestamp("2011-11-25")
APPROVED = {r["file"] for r in CA.rows() if r["status"] == "APPROVED"}
BANDS = ["Large", "Mid", "Small and below"]
RANK = "Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_rank_panel_from_2013-12.csv"
MEMB = "Historical Data/extended_2026-11-12/tags/membership_panel.csv"
SYMB = "Historical Data/extended_2026-11-12/symbology/symbology_changes.csv"


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


def latest(s: pd.Series, d: pd.Timestamp):
    i = s.index.searchsorted(d, side="right") - 1
    assert i >= 0, f"no row on or before {d.date()}"
    return s.iloc[i], s.index[i]


def main():
    cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(need(
        "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"))["date"])))
    assert T0 in cal_all and END in cal_all, "T0 or END is not a D26 session"
    cal = cal_all[(cal_all >= T0) & (cal_all <= END)]

    sig = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(need(f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx"), parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].astype(str).sort_index()
        if n == "SC100":
            s = s[s.index >= SC100_FROM]
        sig[n] = s
    tl = TagLookup.from_files(need(RANK), need(MEMB), need(SYMB))
    assert tl.cutoff > END, "membership cutoff inside the window: not expected"

    # decision dates (shared by the four books: one calendar)
    iso = cal.isocalendar()
    last = pd.Series(cal, index=cal).groupby([iso.year.values, iso.week.values]).max().values
    dates_all = [cal[0]] + [pd.Timestamp(x) for x in sorted(last) if pd.Timestamp(x) > cal[0]]
    sig_rows, stale = {}, 0
    for d in dates_all:
        trip = []
        for n, s in sig.items():
            v, dt = latest(s, d)
            assert dt <= d
            stale += int((d - dt).days > 6)
            trip.append(int(v == "BUY"))
        sig_rows[d] = tuple(trip)

    out = {"T0": str(T0.date()), "END": str(END.date()), "calendar": "D26", "sessions": len(cal),
           "decisions": len(dates_all), "decisions_with_master_row_older_than_6_days": stale,
           "tag_cutoff_membership": str(tl.cutoff.date()), "rank_panel": RANK, "books": {}}
    tag_rows, rows_print = [], []
    for bno, b in enumerate(BOOKS):
        wm = pd.read_csv(need(f"data/holdings_matrix/{b}_holding_weight_matrix.csv"), parse_dates=["rebalance_date"]).set_index("rebalance_date")
        src = pd.read_csv(need(f"data/holdings_matrix/{b}_holding_weight_sources.csv"), parse_dates=["rebalance_date"])
        skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
        wm = wm[~wm.index.isin(skipped)].sort_index()
        cols = pd.read_csv(need(f"data/holdings_matrix/{b}_columns.csv")).set_index("stock")
        colmap = cols["ISIN"].to_dict()
        # T0 = the first basket effective on or after FIRST_PRICE
        t0b = wm.index[wm.index >= FIRST_PRICE][0]
        first_sess = cal_all[cal_all.searchsorted(t0b)]
        assert first_sess == T0, f"{b}: first basket on/after {FIRST_PRICE.date()} takes effect {first_sess.date()}, not T0"
        bsk = wm[(wm.index >= T0) & (wm.index <= END)]
        res = {"baskets_T0_to_END": len(bsk), "basket_changes_after_T0": len(bsk) - 1, "skipped_dropped": len(skipped),
               "last_basket": str(bsk.index[-1].date())}

        # the basket tag table: each basket's stocks as of its relevant date
        unranked_baskets = []
        for adate, row in bsk.iterrows():
            s_first = cal_all[cal_all.searchsorted(adate)]
            info = s_first if s_first == T0 else cal_all[cal_all.searchsorted(s_first) - 1]
            held = row[row > 0]
            w = held / held.sum()
            for stock, wi in w.items():
                t = tl.tag(colmap[stock], info)
                tag_rows.append({"parent": b, "available_date": str(adate.date()), "first_session": str(s_first.date()),
                                 "tag_date": str(info.date()), "stock": stock, "isin": colmap[stock], "listed_weight_raw": float(held[stock]),
                                 "weight_renormalised": float(wi), "band": t["band"], "source": t["source"], "snapshot": t["snapshot"],
                                 "rank": t["detail"], "via": t["via"]})
                if t["source"] == "unranked":
                    unranked_baskets.append(f"{stock} {colmap[stock]} basket {adate.date()} (tag date {info.date()}, snapshot {t['snapshot']})")
        res["unranked_in_basket_table"] = unranked_baskets

        for win, start in (("full", T0), ("r2", R2_START)):
            c0 = cal_all[cal_all.searchsorted(start)]
            dates = [c0] + [d for d in dates_all if d > c0]
            st, basket, kept, shares, srcs, unr = [], [], [], [], [], set()
            for d in dates:
                st.append(sig_rows[d] if d in sig_rows else tuple(int(latest(s, d)[0] == "BUY") for s in sig.values()))
                i = wm.index.searchsorted(d, side="right") - 1
                row = wm.iloc[i]
                held = row[row > 0]
                w = held / held.sum()
                tags = [tl.tag(colmap[s], d) for s in held.index]
                bands = [t["band"] for t in tags]
                srcs += [t["source"] for t in tags]
                unr |= {f"{s} ({colmap[s]})" for s, t in zip(held.index, tags) if t["source"] == "unranked"}
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
            rec = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "weeks": n, "first_state": "".join("B" if x else "S" for x in st[0]),
                   "whole_book_IN_weeks": int(sum(all_buy)), "all_SELL_weeks": int(sum(all_sell)), "mixed_weeks": int(sum(mixed)),
                   "mixed_spells": len(runs(mixed)), "mixed_spell_lengths": runs(mixed),
                   "patterns_N100_MC100_SC100": pat, "flips_per_index": flips,
                   "events_coarse_upper_bound": len(events), "events_signal_flip": len(trig_flip), "events_basket_change": len(trig_bask),
                   "events_in_mixed_weeks": int(sum(1 for k in events if mixed[k])),
                   "mixed_weeks_with_partial_equity": int(sum(1 for x in mk if 0 < x < 1)),
                   "mean_kept_share_in_mixed_weeks": float(np.mean(mk)) if mk else None,
                   "mean_band_share_all_weeks": {k: float(np.mean([s[k] for s in shares])) for k in BANDS},
                   "tag_source_holding_weeks": {k: int(v) for k, v in pd.Series(srcs).value_counts().items()},
                   "unranked_holdings_at_decisions": sorted(unr)}
            res[win] = rec
            rows_print.append((b, win, rec))
        out["books"][b] = res

    ev = AA / "tests" / "T12" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    tt = pd.DataFrame(tag_rows)
    tt.to_csv(ev / "basket_tags_2014-09_2019-01.csv", index=False, lineterminator="\n")
    out["basket_tag_table"] = {"file": "tests/T12/evidence/basket_tags_2014-09_2019-01.csv", "rows": len(tt),
                               "band_rows": tt["band"].value_counts().to_dict(), "source_rows": tt["source"].value_counts().to_dict()}
    p = Path(__file__).parent / "logs"
    p.mkdir(exist_ok=True)
    (p / "step_1_counts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"window {T0.date()} -> {END.date()}, {len(cal)} D26 sessions, {len(dates_all)} decisions, stale Master rows {stale}, tag cutoff {out['tag_cutoff_membership']}")
    for b in BOOKS:
        r = out["books"][b]
        print(f"{b}: baskets {r['baskets_T0_to_END']} ({r['basket_changes_after_T0']} changes), last {r['last_basket']}; unranked in basket table: {r['unranked_in_basket_table'] or 'none'}")
    for b, win, r in rows_print:
        print(f"{b} {win}: {r['start']} -> {r['end']}, {r['weeks']} weeks, first {r['first_state']} | whole-book IN {r['whole_book_IN_weeks']}, all SELL {r['all_SELL_weeks']}, "
              f"mixed {r['mixed_weeks']} in {r['mixed_spells']} stretches {r['mixed_spell_lengths']} | partial-equity mixed weeks {r['mixed_weeks_with_partial_equity']}, "
              f"mean kept {r['mean_kept_share_in_mixed_weeks'] if r['mean_kept_share_in_mixed_weeks'] is None else round(r['mean_kept_share_in_mixed_weeks'], 3)} | "
              f"events <= {r['events_coarse_upper_bound']} (flip {r['events_signal_flip']}, basket {r['events_basket_change']}, in mixed weeks {r['events_in_mixed_weeks']}) | flips {r['flips_per_index']}")
        print(f"      patterns {r['patterns_N100_MC100_SC100']}; band share {({k: round(v, 3) for k, v in r['mean_band_share_all_weeks'].items()})}; "
              f"tag sources {r['tag_source_holding_weeks']}; unranked {r['unranked_holdings_at_decisions'] or 'none'}")
    print(f"basket tag table: {len(tt)} rows, bands {out['basket_tag_table']['band_rows']}, sources {out['basket_tag_table']['source_rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
