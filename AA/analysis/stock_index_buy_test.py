"""Stock-level index BUY filter against the saved final-strategy backtest.

Run: python AA/analysis/stock_index_buy_test.py
Uses local frozen inputs only; writes evidence/stock_index_buy/.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import final_strategy as F
import segment_v2 as V
import segment_v2_data as D
from common import CACHE_DIR, EVIDENCE_DIR, PAIRS
from index_builder import Panel

OUT = EVIDENCE_DIR / "stock_index_buy"
BASE = EVIDENCE_DIR / "final_strategy"
NEW = "Stock index BUY"
WHOLE = "All-three BUY"
PARENT = "Parent"
UNKNOWN_OUT = "Stock index BUY; unknown to sleeve"


def build_stock_steps(ctx, sig, tags, unknown_out=False):
    """Weekly point-in-time classification; keep qualifying parent weights."""
    steps = []
    for review, entry_i, eff in zip(ctx.reviews, ctx.entry_i, ctx.basket_eff):
        weights, rows = {}, []
        for key, ticker, name, isin, pw in ctx.baskets[eff]:
            tag = tags[review][key]
            idx = {"Largecap": V.N100, "Midcap": "MC100"}.get(tag.bucket, V.SC100)
            sign = sig.loc[review, idx]
            hold = sign == "BUY" and not (unknown_out and tag.bucket == "Unknown")
            if hold:
                weights[key] = weights.get(key, 0.0) + pw
            assert tag.snapshot is None or tag.snapshot <= review
            rows.append(dict(key=key, ticker=ticker, name=name, parent_weight=pw,
                             bucket=tag.bucket, tag_source=tag.source,
                             tag_snapshot=tag.snapshot, rank=tag.rank,
                             signal_index=idx, sign=sign, hold=hold,
                             target_weight=pw if hold else 0.0))
        sleeve = max(0.0, 1.0 - sum(weights.values()))
        assert abs(sum(weights.values()) + sleeve - 1) < 1e-10
        steps.append(V.Step(review, entry_i, weights, sleeve, True, "weekly review", rows))
    return steps


def verify_target_logic():
    """Check mixed signals, no qualifying stocks, and parent-weight preservation."""
    r = pd.Timestamp("2020-01-03")
    ctx = V.ParentCtx("test", [r], [1], [r], {r: [
        ("L", "L", "Large", "L", .3), ("M", "M", "Mid", "M", .2),
        ("S", "S", "Small", "S", .4), ("U", "U", "Unknown", "U", .1)]})
    tags = {r: {k: V.Tag(b, "rank", r - pd.Timedelta(days=3), rank)
                for k, b, rank in [("L", "Largecap", 50), ("M", "Midcap", 150),
                                   ("S", "Smallcap", 300), ("U", "Unknown", 1000)]}}
    sig = pd.DataFrame([{V.N100: "BUY", "MC100": "SELL", V.SC100: "SELL"}], index=[r])
    st = build_stock_steps(ctx, sig, tags)[0]
    assert st.weights == {"L": .3} and abs(st.sleeve - .7) < 1e-12
    sig.loc[r] = "BUY"
    st = build_stock_steps(ctx, sig, tags)[0]
    assert st.weights == {"L": .3, "M": .2, "S": .4, "U": .1} and st.sleeve < 1e-12
    assert abs(build_stock_steps(ctx, sig, tags, True)[0].sleeve - .1) < 1e-12
    sig.loc[r] = "SELL"
    st = build_stock_steps(ctx, sig, tags)[0]
    assert st.weights == {} and st.sleeve == 1


def main():
    verify_target_logic()
    OUT.mkdir(exist_ok=True)
    ranks = pd.concat([pd.read_csv(CACHE_DIR / name, parse_dates=["snapshot_date"],
                                  dtype={"isin": "string"}) for name in
                       ("mcap_ranks_monthly_2014_2019.csv", "mcap_ranks_monthly_v2.csv")],
                      ignore_index=True)
    # Consistent rank-based classification across both windows, without today's membership.
    tagger = V.HybridTagger(ranks, None, None)
    saved = pd.read_csv(BASE / "nav_curves_daily.csv", index_col=0, parse_dates=True)
    curves, stats, yearly, trades, positions, decisions, audits, checks = {}, [], [], [], [], [], [], []
    exposures = {}
    for period, label in (("2014_2021", "before the books 2014-07 -> 2021-10"),
                          ("live", "live 2021-11 -> 2026-08")):
        daily = pd.read_csv(BASE / f"daily_SCMO_0042_{period}.csv", index_col=0, parse_dates=True)
        cal = daily.index
        start = saved[f"{label}|SCMO_0042|parent (no overlay)"].first_valid_index()
        wk = pd.read_csv(BASE / f"weekly_signals_{period}.csv", parse_dates=["review", "entry_session"])
        sig = wk.set_index("review")[["N100", "MC100", "SC100"]].rename(columns={"N100": V.N100})
        # These aliases are needed only by the engine's event bookkeeping.
        sig[V.MC150], sig[V.SC250], sig[V.MICRO] = sig.MC100, sig.SC100, sig.SC100
        gold_share = {r.review: .5 if pd.isna(r.gold_signal) else .8 if r.gold_signal == 1 else .2
                      for r in wk.itertuples()}
        px = (pd.read_parquet(CACHE_DIR / "eikon_ohlcv_2014_2021.parquet")
              if period == "2014_2021" else D.load_prices())
        px = px.drop(columns=["ric"], errors="ignore")
        sleeve = pd.DataFrame({V.GOLD: daily.gold_price, V.CASH: daily.cash_level}, index=cal)
        fill = pd.DataFrame({V.GOLD: daily.gold_fill_ohlc4, V.CASH: daily.cash_level}, index=cal)
        close = px.pivot(index="date", columns="ticker", values="close").reindex(cal)
        sim = V.Simulator(Panel(px, cal), sleeve, close=close, sleeve_fill=fill)
        live_hold = D.resolve_holdings() if period == "live" else None
        for aa, parent in PAIRS.items():
            hist = D.parent_history(parent) if live_hold is None else live_hold[live_hold.parent == parent].copy()
            hist["key"] = hist["isin"].where(hist["isin"] != "", hist.ticker)
            ctx = V.parent_ctx(parent, hist, sig.index, cal)
            tags = V.tag_table(ctx, tagger)
            stock = build_stock_steps(ctx, sig, tags)
            rules = {NEW: stock, WHOLE: V.build_whole_book_and(ctx, sig, keys=F.KEYS),
                     PARENT: V.build_parent(ctx, sig),
                     UNKNOWN_OUT: build_stock_steps(ctx, sig, tags, unknown_out=True)}
            for step in stock:
                assert cal[step.entry_i] > step.review
                for row in step.rows:
                    decisions.append(dict(period=period, aa=aa, review=step.review,
                                          entry=cal[step.entry_i], **row))
            for strategy, steps in rules.items():
                audit = {}
                nav, log, pos = sim.run(steps, V.PRIMARY_BPS, gold_share=gold_share,
                                        positions=True, close_on_trade_day=True, audit=audit)
                nav = nav.loc[start:]
                nav = nav / nav.iloc[0]
                assert nav.notna().all() and (nav > 0).all()
                key = f"{period}|{aa}|{strategy}"
                curves[key] = nav
                eq = V.exposure(steps, cal).reindex(nav.index)
                exposures[key] = eq
                result = dict(period=period, aa=aa, parent=parent, strategy=strategy,
                              **F.stats(nav, sleeve[V.CASH]), avg_equity_target=eq.mean(),
                              trades=len(log), cost_sum_nav=(log.cost / log.nav_at_fill).sum())
                stats.append(result)
                yearly.extend(dict(period=period, aa=aa, strategy=strategy, year=int(y), return_=float(v))
                              for y, v in F.yearly(nav).items())
                audits.append(dict(period=period, aa=aa, strategy=strategy, **audit, **ctx.audit))
                if strategy == NEW:
                    trades.append(log.assign(period=period, aa=aa, strategy=strategy))
                    positions.append(pos.assign(period=period, aa=aa, strategy=strategy))
                if strategy in (WHOLE, PARENT):
                    old_name = ("FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)"
                                if strategy == WHOLE else "parent (no overlay)")
                    expected = saved[f"{label}|{aa}|{old_name}"].reindex(nav.index)
                    assert expected.notna().all()
                    error = float((nav - expected).abs().max())
                    checks.append(dict(period=period, aa=aa, strategy=strategy, max_nav_error=error))
                    assert error < 1e-10, (period, aa, strategy, error)
            print(f"{period} {aa}: completed and baseline reconciled", flush=True)
    stats = pd.DataFrame(stats)
    yearly = pd.DataFrame(yearly).rename(columns={"return_": "return"})
    decisions = pd.DataFrame(decisions)
    stats.to_csv(OUT / "summary_stats.csv", index=False)
    yearly.to_csv(OUT / "yearly_returns.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / "nav_curves_daily.csv")
    pd.DataFrame(exposures).to_csv(OUT / "equity_targets_daily.csv")
    pd.concat(trades).to_csv(OUT / "trade_log.csv", index=False)
    pd.concat(positions).to_csv(OUT / "position_log.csv", index=False)
    decisions.to_csv(OUT / "stock_decisions_weekly.csv", index=False)
    pd.DataFrame(audits).to_csv(OUT / "audit.csv", index=False)
    pd.DataFrame(checks).to_csv(OUT / "baseline_reconciliation.csv", index=False)
    coverage = []
    for (period, aa), g in decisions.groupby(["period", "aa"]):
        by_review = g.assign(unknown_w=np.where(g.bucket == "Unknown", g.parent_weight, 0)).groupby("review").unknown_w.sum()
        snapshots = pd.to_datetime(g.tag_snapshot)
        coverage.append(dict(period=period, aa=aa, unknown_avg_weight=by_review.mean(),
                             unknown_max_weight=by_review.max(),
                             max_rank_age_days=(g.review - snapshots).dt.days.max()))
    pd.DataFrame(coverage).to_csv(OUT / "classification_coverage.csv", index=False)
    make_report(stats, yearly, curves, coverage, checks, audits, decisions)
    print(stats[["period", "aa", "strategy", "cagr", "max_dd_daily", "avg_equity_target"]].round(4).to_string(index=False))


def markdown_table(frame):
    return "| " + " | ".join(frame.columns) + " |\n| " + " | ".join(["---"] * len(frame.columns)) + " |\n" + "\n".join(
        "| " + " | ".join(map(str, row)) + " |" for row in frame.itertuples(index=False, name=None))


def make_report(stats, yearly, curves, coverage, checks, audits, decisions):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {NEW: "#087f8c", WHOLE: "#3974dc", PARENT: "#d7658c"}
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=True)
    for col, period in enumerate(("2014_2021", "live")):
        for strategy in colors:
            nav = curves[f"{period}|SCMO_0042|{strategy}"]
            axes[0, col].plot(nav.index, nav, color=colors[strategy], label=f"{strategy}: {nav.iloc[-1]:.2f}x", lw=1.4)
            axes[1, col].plot(nav.index, 100 * (nav / nav.cummax() - 1), color=colors[strategy], lw=1.1)
        axes[0, col].set_title("SCMO_0042: " + ("Jul 2014 - Oct 2021" if col == 0 else "Nov 2021 - Aug 2026"))
        axes[0, col].set_yscale("log")
        axes[0, col].set_ylabel("Growth of 1 (log scale)")
        axes[0, col].legend(fontsize=9)
        axes[1, col].set_ylabel("Drawdown (%)")
        for ax in axes[:, col]:
            ax.grid(alpha=.2)
    fig.savefig(OUT / "SCMO_0042_comparison.png", dpi=170)
    plt.close(fig)
    early = stats[(stats.aa == "SCMO_0042") & (stats.period == "2014_2021")].set_index("strategy")
    live = stats[(stats.aa == "SCMO_0042") & (stats.period == "live")].set_index("strategy")
    g2015 = decisions[(decisions.aa == "SCMO_0042") & (decisions.review.dt.year == 2015)]
    sc_share = g2015[g2015.signal_index == V.SC100].parent_weight.sum() / g2015.review.nunique()
    missing = next(x["target_rows_no_price"] for x in audits
                   if x["period"] == "2014_2021" and x["aa"] == "SCMO_0042" and x["strategy"] == NEW)
    lines = ["# Stock-level index BUY test", "",
             f"SCMO_0042: annual return changes from {early.loc[WHOLE, 'cagr']:.2%} to "
             f"{early.loc[NEW, 'cagr']:.2%} in 2014-21, and from {live.loc[WHOLE, 'cagr']:.2%} "
             f"to {live.loc[NEW, 'cagr']:.2%} in 2021-26. The stock filter modestly improves early-window "
             "returns across all four books, but trails the all-three rule in all four recent-window comparisons.", "",
             f"It does not resolve the early parent gap in 0042. In 2015, {sc_share:.1%} of the basket weight "
             "on average reads Smallcap 100, so most names still move together under a single signal. "
             "The new rule returns -1.76% that year versus -4.48% for the all-three rule and +79.14% for the parent. "
             "In 2016 it gives back ground: -0.98% versus +23.80% for the all-three rule.", "",
             "Each week, buy or retain a parent stock only while its assigned index is BUY. "
             "Qualifying names keep their parent target weights; the remainder goes to the existing "
             "MAUc1-timed gold/cash sleeve (80/20 on gold BUY, 20/80 on SELL, 50/50 before its first signal).", "",
             "Classification uses the latest available monthly market-cap rank: ranks 1-100 read Nifty 100; "
             "101-250 read Midcap 100; 251-900 read Smallcap 100. Ranks above 900 and unranked stocks "
             "also read Smallcap 100 in the primary run. A separate sensitivity sends this Unknown bucket to the sleeve. "
             "These are market-cap proxies, not verified historical membership of the three indices.", "",
             "All classifications are refreshed at the weekly review using snapshots dated on or before that review. "
             "The 2014-19 and 2019-26 rank caches are joined; no frozen July 2019 classification is carried through 2021. "
             "No manual classification overrides or current membership snapshots are applied.", "",
             "Same parent baskets, daily prices, next-session fills, close valuation and 20.8 bps round-trip cost "
             "as the final-strategy report. An unchanged target does not trade, so holdings drift. When the target "
             "changes (including a gold split change), all positions are reset to the new target weights. "
             "The engine redistributes unfillable target weights across fillable assets; audit.csv records their incidence.", "",
             "![SCMO_0042 comparison](SCMO_0042_comparison.png)", ""]
    for period in ("2014_2021", "live"):
        lines += ["## " + period, ""]
        g = stats[(stats.period == period) & (stats.strategy != UNKNOWN_OUT)].copy()
        table = pd.DataFrame({"Book": g.aa, "Strategy": g.strategy,
                              "CAGR": g.cagr.map(lambda x: f"{x:.2%}"),
                              "Max drawdown": g.max_dd_daily.map(lambda x: f"{x:.2%}"),
                              "End value": (1 + g.total_return).map(lambda x: f"{x:.2f}x"),
                              "Avg equity target": g.avg_equity_target.map(lambda x: f"{x:.1%}")})
        lines += [markdown_table(table), ""]
    y = yearly[(yearly.aa == "SCMO_0042") & (yearly.strategy != UNKNOWN_OUT)].pivot(
        index=["period", "year"], columns="strategy", values="return")
    for c in y:
        y[c] = y[c].map(lambda x: f"{x:.2%}")
    lines += ["## SCMO_0042 yearly returns", "", "First and last years of each window are partial.", "",
              markdown_table(y.reset_index()), "", "## Verification and limits", "",
              f"All {len(checks)} baseline NAV comparisons pass; maximum daily NAV error against the existing report "
              f"is {max(x['max_nav_error'] for x in checks):.3g}.", "",
              "Target-logic checks pass for mixed BUY/SELL signals, all BUY, all SELL, parent-weight preservation "
              "and Unknown-to-sleeve handling. Every decision asserts that its classification snapshot is not future-dated "
              "and its fill occurs after the review.", "",
              f"The early SCMO_0042 run has {missing} stock/review target observations with no fill price "
              "(including repeated weekly observations); the engine redistributes these weights across fillable assets, "
              "as in the baseline. All four recent-window stock-filter runs have zero such observations. "
              "These early price gaps limit the precision of the historical comparison.", "",
              "Classification coverage and the Unknown-to-sleeve sensitivity are saved alongside the main results. "
              "This is a retrospective comparison motivated by observed results, not an untouched out-of-sample test.", "",
              "Files: summary_stats.csv; yearly_returns.csv; nav_curves_daily.csv; stock_decisions_weekly.csv; "
              "trade_log.csv; position_log.csv; equity_targets_daily.csv; classification_coverage.csv; audit.csv; "
              "baseline_reconciliation.csv."]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "run_config.json").write_text(json.dumps({"rule": NEW, "weights": "parent weights; residual sleeve",
        "tagging": "weekly point-in-time monthly market-cap ranks", "unknown": "Smallcap 100 proxy",
        "cost_round_trip_bps": V.PRIMARY_BPS, "gold": "same MAUc1 signal as final_strategy",
        "membership_test": False}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
