# Why the stock-level index filter missed SCMO_0042's 2015 gains

The parent's 79.14% annual gain came from its selected stocks. Eligibility under the new rule comes from each stock's assigned broad-index signal. The selected stocks can rally much faster than that index, and the index must cross its supertrend threshold before the rule buys.

Assignments are historical market-cap proxies, not verified index membership. They can change during the year. stock_signal_mapping.csv lists every name and assignment; every_stock_weekly.csv gives the exact classification and decision each week.

## Where returns were missed

| start | end | Parent | Stock index BUY |
| --- | --- | --- | --- |
| 2014-12-31 | 2015-12-31 | 79.14% | -1.76% |
| 2015-05-11 | 2015-07-17 | 23.21% | -4.06% |
| 2015-09-07 | 2015-12-24 | 29.87% | -2.46% |
| 2015-06-08 | 2015-07-17 | 27.30% | -2.28% |

Returns are between the stated daily closes. The two defensive stretches are disjoint; the June example is inside the first stretch. Do not add these returns. All three index signals were SELL for reviews 8 May through 10 July (execution from 11 May), and 4 September through 18 December (execution from 7 September). Smallcap 100 flipped BUY on 24 December, for execution 28 December.

## Actual June basket

At the 5 June review, all 15 parent positions had equal 6.67% target weights: 13 read Smallcap 100 and two read Midcap 100. Both signals were SELL, so all 15 were excluded. The parent bought its new June basket on 8 June while the stock-level rule remained in gold/cash.

Stock close returns, 8 June to 17 July (not full-year returns or portfolio contribution percentages):

| ticker | signal_index | return_jun8_jul17 |
| --- | --- | --- |
| RAJESHEXPO | MC100 | 97.09% |
| SANGAMIND | SC100 | 48.45% |
| WELSPUNLIV | MC100 | 44.75% |
| VINDHYATEL | SC100 | 40.72% |
| TVSSRICHAK | SC100 | 36.61% |
| ICIL | SC100 | 30.88% |
| GARFIBRES | SC100 | 28.92% |
| GRANULES | SC100 | 19.14% |
| SIYSIL | SC100 | 14.71% |
| INSECTICID | SC100 | 12.10% |
| KPRMILL | SC100 | 10.17% |
| SMSPHARMA | SC100 | 9.71% |
| BBTC | SC100 | 7.80% |
| SONATSOFTW | SC100 | 6.29% |
| TVSHLTD | SC100 | 2.24% |

## Why SELL persisted during a rally

Smallcap 100 closed at 5,502.65 on 10 July, below its supertrend threshold of 5,685.74, so it remained SELL. On 17 July it closed at 5,686.45 and flipped BUY. Re-entry was the next session, 20 July, after much of the parent-stock rally. Smallcap 100 was SELL at 33 of 52 reviews in 2015.

The rule did allow the stocks through when their own assigned indices were BUY: at the 27 March review Nifty 100 was SELL, but all 15 stocks read Midcap 100 or Smallcap 100, both BUY; the new rule therefore held 100% stocks. This confirms the Nifty 100 whole-portfolio veto was removed. The remaining missed returns arise when the stocks' own assigned index signals are SELL.

Sources: saved parent and stock-filter daily NAVs, weekly stock decisions, Eikon stock closes, and frozen production Master index workbooks. Figures describe the saved backtest.