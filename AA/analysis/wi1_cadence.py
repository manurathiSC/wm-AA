# -*- coding: utf-8 -*-
"""
Work item 1, as descoped: (a) confirm the semi-annual bucket indices track the
official series well enough that cadence is settled, and (b) decide whether a
self-built microcap series should fill the gap at the start of the window.

Both came back negative, and both negatives are useful.

(a) No bucket clears the ~97% weekly SIGN bar; they land at 83-88%. The bar is
    not reachable by any series built from daily levels, and the reason is
    measurable rather than speculative: rebuilding the OFFICIAL series from its
    own closes -- identical constituents, weighting and cadence, only the
    intraday high/low removed -- already costs ~10 points of signal agreement,
    because weekly true range shrinks ~25%, narrowing the supertrend bands and
    making the latch flip more often. That accounts for most of the shortfall;
    equal weighting accounts for the rest. None of it indicts the cadence
    choice, and none of it touches the backtest, which reads SIGN from
    `Master_*.xlsx` computed on official levels. Cadence moves bucket
    assignment only.

(b) The self-built microcap extension is WORSE than the fallback it was meant
    to replace. Scored against the official microcap signal, the synthetic
    series agrees 83.1% while the Smallcap 250 signal -- production's own
    convention -- agrees 97.5%, winning head-to-head 35 to 1. So the extension
    is not used, and the 12 uncovered review weeks fall back to Smallcap 250
    and are flagged.

Writes to `evidence/segment_v1/`:
    index_cadence_comparison.csv    one row per bucket, synth vs official
    index_recon_log.csv             constituents requested / filled / dropped
    no_intraday_penalty.csv         the ~10-point cost, isolated
    microcap_extension.csv          the self-built microcap level series
    microcap_extension_bakeoff.csv  synthetic vs Smallcap 250 fallback
    microcap_extension_report.csv   the decision and what it rests on
"""

from __future__ import annotations

import pandas as pd

from common import EVIDENCE_DIR
from index_builder import (
    BUCKET_BANDS,
    OFFICIAL_SHEET,
    Panel,
    build_index,
    compare,
    members_from_ranks,
    synth_daily_frame,
    universe_ohlcv,
    weekly_signal,
)
from mcap_ranks import load_cache
from supertrend import load_index_ohlcv, to_weekly

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"

WINDOW_START = pd.Timestamp("2021-11-01")
WINDOW_END = pd.Timestamp("2026-08-21")
CALENDAR_CSV = (
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation\Data\calendar.csv"
)
MASTER_MICRO_START = pd.Timestamp("2022-02-18")   # Master_NiftyMicrocap250.xlsx


def session_calendar() -> pd.DatetimeIndex:
    """
    Window sessions plus ONE session of lead-in. The lead-in is not cosmetic:
    measurement has to start on a session where NAV is exactly 1.0 and no fill
    has happened yet, otherwise the first session's move is dropped from the
    series (F-M08), and that error is not uniform in sign.
    """
    d = pd.read_csv(CALENDAR_CSV)
    idx = pd.DatetimeIndex(pd.to_datetime(d["date"]).unique()).sort_values()
    idx = idx[idx <= WINDOW_END]
    prior = idx[idx < WINDOW_START]
    if not len(prior):
        raise ValueError("no session before the window start in calendar.csv")
    return idx[idx >= prior[-1]]


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    cal = session_calendar()
    print(f"calendar: {len(cal)} sessions  {cal.min().date()} -> {cal.max().date()}")

    ranks = load_cache("semiannual")
    needed = sorted(ranks[ranks["rank"] <= max(h for _, h in BUCKET_BANDS.values())]
                    ["ticker"].unique())
    print(f"fetching OHLCV for {len(needed)} tickers ...")
    ohlcv = universe_ohlcv(needed)
    print(f"  {len(ohlcv):,} price rows, {ohlcv['ticker'].nunique()} tickers")

    panel = Panel(ohlcv, cal)

    rows, logs, levels = [], [], {}
    for bucket in BUCKET_BANDS:
        members = members_from_ranks(ranks, bucket, cal, WINDOW_START)
        level, log = build_index(panel, members)
        levels[bucket] = level
        logs.append(log.assign(bucket=bucket))

        official = load_index_ohlcv(OFFICIAL_SHEET[bucket])
        rows.append(compare(level, official, bucket))
        print(f"  built {bucket:9s} {len(members)} reconstitutions")

    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(EVIDENCE_SUBDIR / "index_cadence_comparison.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(
        EVIDENCE_SUBDIR / "index_recon_log.csv", index=False)

    show = cmp_df[["bucket", "sessions", "corr_daily_returns", "tracking_error_ann",
                   "cagr_synth", "cagr_official", "weeks_compared",
                   "weekly_sign_agreement", "weeks_sign_differs"]].copy()
    print("\n(a) CONFIRMATORY -- semi-annual synthetic vs official")
    print(show.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    bar = 0.97
    below = cmp_df[cmp_df["weekly_sign_agreement"] < bar]["bucket"].tolist()
    print(f"\nbar = {bar:.0%} weekly SIGN agreement; below bar: "
          f"{below if below else 'none'}")

    # ── Why the bar is unreachable: the no-intraday penalty ────────────────
    # A synthetic series has one level per session, so its weekly high and low
    # are the max and min of daily levels, not true intraday extremes. Measure
    # that in isolation by rebuilding the OFFICIAL series from its own closes:
    # same constituents, same weighting, same cadence, only H/L differ.
    pen = []
    for bucket, sheet in OFFICIAL_SHEET.items():
        d = load_index_ohlcv(sheet)
        d = d[(d.index >= cal.min()) & (d.index <= WINDOW_END)]
        true_sig = weekly_signal(d).dropna()
        flat_sig = weekly_signal(synth_daily_frame(d["close"])).dropna()
        j = true_sig.index.intersection(flat_sig.index)
        wt, wf = to_weekly(d), to_weekly(synth_daily_frame(d["close"]))
        pen.append({
            "bucket": bucket, "sheet": sheet, "weeks": int(len(j)),
            "sign_agreement_flat_vs_true": float((true_sig.loc[j] == flat_sig.loc[j]).mean()),
            "weeks_differ": int((true_sig.loc[j] != flat_sig.loc[j]).sum()),
            "weekly_TR_shrinkage": float(1 - wf["TR"].mean() / wt["TR"].mean()),
        })
    pen_df = pd.DataFrame(pen)
    pen_df.to_csv(EVIDENCE_SUBDIR / "no_intraday_penalty.csv", index=False)
    print("\nWHY -- cost of having no intraday high/low, measured on the "
          "official series itself")
    print(pen_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    # ── (b) microcap extension: bake-off, not assumption ───────────────────
    micro = levels["Microcap"]
    official_micro = load_index_ohlcv(OFFICIAL_SHEET["Microcap"])
    off_start = official_micro.index.min()

    sig_synth = weekly_signal(synth_daily_frame(micro)).dropna()
    sig_off = weekly_signal(official_micro).dropna()
    sig_sc = weekly_signal(load_index_ohlcv(OFFICIAL_SHEET["Smallcap"])).dropna()

    micro.rename("level").to_frame().assign(
        source=["extension" if d < off_start else "overlap" for d in micro.index]
    ).to_csv(EVIDENCE_SUBDIR / "microcap_extension.csv")

    # The extension is only worth using if it beats the fallback it replaces.
    # Both are scored against the official microcap signal on its own history.
    rows_b = []
    for name, s in [("self_built_synthetic", sig_synth),
                    ("smallcap250_production_fallback", sig_sc)]:
        j = sig_off.index.intersection(s.index)
        rows_b.append({"candidate": name, "weeks_scored": int(len(j)),
                       "agreement_vs_official_microcap": float((sig_off.loc[j] == s.loc[j]).mean()),
                       "weeks_differ": int((sig_off.loc[j] != s.loc[j]).sum())})
    bake = pd.DataFrame(rows_b)

    j = sig_off.index.intersection(sig_sc.index).intersection(sig_synth.index)
    synth_ok = (sig_synth.loc[j] == sig_off.loc[j])
    sc_ok = (sig_sc.loc[j] == sig_off.loc[j])
    gained = sig_synth.index[sig_synth.index < MASTER_MICRO_START]

    winner = bake.loc[bake["agreement_vs_official_microcap"].idxmax(), "candidate"]
    use_extension = winner == "self_built_synthetic"

    rep = pd.DataFrame([{
        "official_history_starts": str(off_start.date()),
        "master_signal_starts": str(MASTER_MICRO_START.date()),
        "synthetic_starts": str(micro.index.min().date()),
        "review_weeks_uncovered": int(len(gained)),
        "uncovered_first": str(gained.min().date()) if len(gained) else None,
        "uncovered_last": str(gained.max().date()) if len(gained) else None,
        "sessions_uncovered": int(((micro.index >= WINDOW_START)
                                   & (micro.index < MASTER_MICRO_START)).sum()),
        "synth_right_sc_wrong": int((synth_ok & ~sc_ok).sum()),
        "sc_right_synth_wrong": int((sc_ok & ~synth_ok).sum()),
        "winner": winner,
        "use_extension": use_extension,
        "decision": (
            "USE the self-built extension for the uncovered weeks."
            if use_extension else
            "DO NOT use the self-built extension. It loses to the Smallcap 250 "
            "fallback against the official microcap signal, so shipping it would "
            "put a measurably worse signal into micro_own. Fall back to Smallcap "
            "250 for the uncovered weeks -- production's own convention -- and "
            "flag them."
        ),
    }])
    bake.to_csv(EVIDENCE_SUBDIR / "microcap_extension_bakeoff.csv", index=False)
    rep.to_csv(EVIDENCE_SUBDIR / "microcap_extension_report.csv", index=False)

    print("\n(b) MICROCAP EXTENSION -- bake-off against the official microcap signal")
    print(bake.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    print(rep.T.to_string(header=False))


if __name__ == "__main__":
    main()
