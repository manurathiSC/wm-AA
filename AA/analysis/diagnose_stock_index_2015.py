"""Explain SCMO_0042's 2015 parent/stock-index-filter gap from saved local data."""
import pandas as pd

import segment_v2_data as D
from common import CACHE_DIR, EVIDENCE_DIR
from stock_index_buy_test import markdown_table


def main():
    root = EVIDENCE_DIR / "stock_index_buy"
    out = root / "diagnosis_2015"
    out.mkdir(exist_ok=True)
    decisions = pd.read_csv(root / "stock_decisions_weekly.csv", parse_dates=["review", "entry"])
    d = decisions[(decisions.aa == "SCMO_0042") & (decisions.review.dt.year == 2015)].copy()
    d.to_csv(out / "every_stock_weekly.csv", index=False)
    mapping = d.groupby(["ticker", "name", "signal_index"]).agg(
        first_review=("review", "min"), last_review=("review", "max"),
        reviews=("review", "count"), buy_reviews=("hold", "sum")).reset_index()
    mapping.to_csv(out / "stock_signal_mapping.csv", index=False)
    curves = pd.read_csv(root / "nav_curves_daily.csv", index_col=0, parse_dates=True)
    periods = []
    for start, end in [("2014-12-31", "2015-12-31"), ("2015-05-11", "2015-07-17"),
                       ("2015-09-07", "2015-12-24"), ("2015-06-08", "2015-07-17")]:
        row = dict(start=start, end=end)
        for strategy in ("Parent", "Stock index BUY"):
            nav = curves[f"2014_2021|SCMO_0042|{strategy}"]
            row[strategy] = nav.loc[end] / nav.loc[start] - 1
        periods.append(row)
    periods = pd.DataFrame(periods)
    periods.to_csv(out / "period_returns.csv", index=False)
    prices = pd.read_parquet(CACHE_DIR / "eikon_ohlcv_2014_2021.parquet")
    close = prices.pivot(index="date", columns="ticker", values="close").ffill()
    basket = d[d.review == "2015-06-05"].copy()
    basket["return_jun8_jul17"] = [close.loc["2015-07-17", k] / close.loc["2015-06-08", k] - 1
                                  for k in basket.key]
    basket = basket.sort_values("return_jun8_jul17", ascending=False)
    basket.to_csv(out / "june_basket_stock_returns.csv", index=False)
    masters = []
    for name in ("Nifty100", "MC100", "SC100"):
        m = pd.read_excel(D.MASTER_DIR / f"Master_{name}.xlsx")
        m["Date"] = pd.to_datetime(m.Date)
        m = m[m.Date.dt.year == 2015][["Date", "Index", "ST", "SIGN"]].assign(index_name=name)
        masters.append(m)
    pd.concat(masters).to_csv(out / "index_signals_and_thresholds.csv", index=False)
    w = pd.read_csv(EVIDENCE_DIR / "final_strategy" / "weekly_signals_2014_2021.csv")
    w = w[w.review.str.startswith("2015")]
    assert (w.SC100 == "SELL").sum() == 33
    assert len(basket) == 15 and (basket.sign == "SELL").all() and not basket.hold.any()
    assert set(basket[basket.signal_index == "MC100"].ticker) == {"RAJESHEXPO", "WELSPUNLIV"}
    assert (basket.signal_index == "SC100").sum() == 13
    shown = basket[["ticker", "signal_index", "return_jun8_jul17"]].copy()
    shown["return_jun8_jul17"] = shown.return_jun8_jul17.map(lambda x: f"{x:.2%}")
    pt = periods.copy()
    for c in ("Parent", "Stock index BUY"):
        pt[c] = pt[c].map(lambda x: f"{x:.2%}")
    text = ["# Why the stock-level index filter missed SCMO_0042's 2015 gains", "",
            "The parent's 79.14% annual gain came from its selected stocks. Eligibility under the new rule "
            "comes from each stock's assigned broad-index signal. The selected stocks can rally much faster "
            "than that index, and the index must cross its supertrend threshold before the rule buys.", "",
            "Assignments are historical market-cap proxies, not verified index membership. They can change "
            "during the year. stock_signal_mapping.csv lists every name and assignment; every_stock_weekly.csv "
            "gives the exact classification and decision each week.", "",
            "## Where returns were missed", "", markdown_table(pt), "",
            "Returns are between the stated daily closes. The two defensive stretches are disjoint; the June "
            "example is inside the first stretch. Do not add these returns. All three index signals were SELL "
            "for reviews 8 May through 10 July (execution from 11 May), and 4 September through 18 December "
            "(execution from 7 September). Smallcap 100 flipped BUY on 24 December, for execution 28 December.", "",
            "## Actual June basket", "",
            "At the 5 June review, all 15 parent positions had equal 6.67% target weights: 13 read Smallcap 100 "
            "and two read Midcap 100. Both signals were SELL, so all 15 were excluded. The parent bought its "
            "new June basket on 8 June while the stock-level rule remained in gold/cash.", "",
            "Stock close returns, 8 June to 17 July (not full-year returns or portfolio contribution percentages):", "",
            markdown_table(shown), "",
            "## Why SELL persisted during a rally", "",
            "Smallcap 100 closed at 5,502.65 on 10 July, below its supertrend threshold of 5,685.74, so it "
            "remained SELL. On 17 July it closed at 5,686.45 and flipped BUY. Re-entry was the next session, "
            "20 July, after much of the parent-stock rally. Smallcap 100 was SELL at 33 of 52 reviews in 2015.", "",
            "The rule did allow the stocks through when their own assigned indices were BUY: at the 27 March "
            "review Nifty 100 was SELL, but all 15 stocks read Midcap 100 or Smallcap 100, both BUY; the new rule "
            "therefore held 100% stocks. This confirms the Nifty 100 whole-portfolio veto was removed. "
            "The remaining missed returns arise when the stocks' own assigned index signals are SELL.", "",
            "Sources: saved parent and stock-filter daily NAVs, weekly stock decisions, Eikon stock closes, "
            "and frozen production Master index workbooks. Figures describe the saved backtest."]
    (out / "explanation.md").write_text("\n".join(text), encoding="utf-8")
    print(pt.to_string(index=False))
    print(shown.to_string(index=False))


if __name__ == "__main__":
    main()
