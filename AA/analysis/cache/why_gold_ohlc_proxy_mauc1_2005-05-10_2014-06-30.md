# why_gold_ohlc_proxy_mauc1_2005-05-10_2014-06-30

Gold proxy for the sessions before GOLDBEES's first approved bar (2014-07-01), built by `data/build_gold_proxy.py`.

- bars: 2765, 2005-05-10 -> 2014-06-30; columns date, open, high, low, close (the layout of D09)
- proxy bar = k x MAUc1 bar, k = 0.0009398832 = GOLDBEES close / MAUc1 close on 2014-07-01; the proxy's returns are MAUc1's returns, nothing fitted or drift-adjusted; the splice day's return equals MAUc1's (-0.001080)
- MAUc1 input: `Historical Data\extended_2026-11-12\MAUc1_from_2003\mauc1_daily_clean_extended.csv` (D24b, sha256 febab21fd818d65d); GOLDBEES: `analysis\cache\why_gold_ohlc_eikon_extended_2026-11-04.parquet` (D09, sha256 3e02141265537443)
- tracking against the real GOLDBEES on 2014-07-01 -> 2026-11-04: daily correlation 0.506 (lag -1 0.028, lag +1 0.435), weekly correlation 0.816, CAGR GOLDBEES 12.88% vs MAUc1 14.22% (gap -1.337 pp/yr)
- daily relation on the overlap: GOLDBEES return ~ 0.497 x MAUc1 return on the day + 0.425 x MAUc1 return the day before (R2 0.436): the MCX evening session after the NSE close puts part of a GOLDBEES day's move into MAUc1's next bar
- the proxy starts 2005-05-10, after the last invalid MAUc1 bar (2004-04-24: a lone 9,207 print on a Saturday; 2005-05-07: a zero close); other odd bars are kept as they are, for example 2014-02-05 (+5.7%, volume 267, reversed the next day, a contract-roll artifact that D24's weekly signal also reads)
- limits: the MCX session ends after the NSE close, so a daily proxy return mixes two NSE days; MAUc1 is a futures series (roll gaps, basis); GOLDBEES nets a fund expense; the proxy is a gold price series, not GOLDBEES
