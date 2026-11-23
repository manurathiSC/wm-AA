# Basket band check: index membership vs market-cap rank (SCMO_0010, SCMO_0029)

**Asked by Manu, 2026-11-13.** Ad-hoc lookup. Not a test, and not an input to any test.

## What was asked
For the 2026-09-11 baskets of SCMO_0010 (15 stocks) and SCMO_0029 (14 stocks), Manu asked for each stock's market-cap category. Two sources were used:

- **Index band.** The stock's index in `public.index_constituents_monthly`. There is no snapshot dated 2026-09-11. The one in force on that date is **2026-09-01**; the next is 2026-10-01. Nifty 100 = Large, Midcap 150 = Mid, Smallcap 250 = Small, Microcap 250 = Micro. Small and Micro together are "Small and below" in the project's tag rule.
- **Rank band.** The stock's rank by market cap on **2026-11-12** (`mcap_scaled_in_cr`) in `public.mcap_based_universe`. It ranks all 3,081 `instrument_class = 'ordinary'` rows on that date, one per ISIN, with 1 = largest. Bands: 1-100 Large, 101-250 Mid, 251-500 Small, 501+ Micro. There is no free-float or liquidity filter.

**Cut-offs on 2026-11-12:**

| Rank | Market cap (Rs cr) |
|---|---:|
| 100 | 116,938 |
| 250 | 36,518 |
| 500 | 13,294 |

**Weights.** The weights are as listed in Manu's Redash screenshots of the 2026-09-11 baskets. Both baskets sum to 1.000.

## SCMO_0010

| Symbol | Weight | Index band (2026-09-01) | Mcap (Rs cr) | Rank | Rank band |
|---|---:|---|---:|---:|---|
| MOTHERSON | 6.66% | Large | 176,288 | 53 | Large |
| ABCAPITAL | 6.67% | Mid | 114,866 | 103 | Mid |
| SAIL | 6.67% | Mid | 73,399 | 155 | Mid |
| WELCORP | 6.67% | Small | 56,852 | 189 | **Mid** |
| GLAND | 6.67% | Small | 54,597 | 196 | **Mid** |
| IPCALAB | 6.66% | Mid | 48,196 | 213 | Mid |
| KARURVYSYA | 6.67% | Small | 36,793 | 246 | **Mid** |
| LALPATHLAB | 6.66% | Small | 33,578 | 260 | Small |
| MANAPPURAM | 6.66% | Small | 30,054 | 283 | Small |
| PNBHOUSING | 6.66% | Small | 29,612 | 286 | Small |
| CEMPRO | 6.67% | Small | 24,447 | 321 | Small |
| GRANULES | 6.67% | Small | 22,927 | 341 | Small |
| EMMVEE | 6.67% | Small | 18,593 | 378 | Small |
| ENGINERSIN | 6.67% | Small | 17,286 | 406 | Small |
| SOUTHBANK | 6.67% | Micro | 16,067 | 430 | **Small** |

| Band | Index band (by weight) | Rank band (by weight) | Change |
|---|---:|---:|---:|
| Large | 6.66% (1 stock) | 6.66% (1 stock) | 0 |
| Mid | 20.00% (3 stocks) | 40.01% (6 stocks) | +20.0 pp |
| Small and below | 73.34% (11 stocks: 10 Small + 1 Micro) | 53.33% (8 stocks) | −20.0 pp |

## SCMO_0029

| Symbol | Weight | Index band (2026-09-01) | Mcap (Rs cr) | Rank | Rank band |
|---|---:|---|---:|---:|---|
| TVSMOTOR | 7.15% | Large | 215,750 | 44 | Large |
| MOTHERSON | 7.15% | Large | 176,288 | 53 | Large |
| LAURUSLABS | 7.14% | Mid | 129,675 | 79 | **Large** |
| NAM-INDIA | 7.14% | Mid | 71,557 | 160 | Mid |
| SAILIFE | 7.14% | Small | 40,480 | 233 | **Mid** |
| KARURVYSYA | 7.15% | Small | 36,793 | 246 | **Mid** |
| ACUTAAS | 7.14% | Small | 32,717 | 264 | Small |
| SYRMA | 7.15% | Small | 29,086 | 291 | Small |
| ABSLAMC | 7.14% | Small | 26,908 | 306 | Small |
| DATAPATTNS | 7.14% | Small | 23,687 | 327 | Small |
| GRANULES | 7.14% | Small | 22,927 | 341 | Small |
| INOXINDIA | 7.14% | Micro | 17,838 | 392 | **Small** |
| SKYGOLD | 7.14% | Micro | 16,263 | 425 | **Small** |
| PGIL | 7.14% | Micro | 12,719 | 515 | Micro |

| Band | Index band (by weight) | Rank band (by weight) | Change |
|---|---:|---:|---:|
| Large | 14.30% (2 stocks) | 21.44% (3 stocks) | +7.1 pp |
| Mid | 14.28% (2 stocks) | 21.43% (3 stocks) | +7.2 pp |
| Small and below | 71.42% (10 stocks: 7 Small + 3 Micro) | 57.13% (8 stocks: 7 Small + 1 Micro) | −14.3 pp |

The baskets are equal-weighted, so percentages by stock count match those by weight to within 0.1 pp.

## What it shows
- **Rank puts more of each basket in Mid and Large than the index lists do.**
  - In SCMO_0010, 20 pp of weight moves from Small to Mid: WELCORP, GLAND and KARURVYSYA.
  - In SCMO_0029, 14.3 pp moves out of Small and below. LAURUSLABS goes from Mid to Large; SAILIFE and KARURVYSYA go from Small to Mid.
- **Stocks near a band line:**
  - KARURVYSYA (rank 246) is about Rs 275 cr above the Mid/Small line.
  - ABCAPITAL (103) is about Rs 2,100 cr short of Large.
  - PGIL (515) is just past rank 500.

## Caveats
- **Different dates.** The index lists are the 2026-09-01 snapshot; the market caps are from 2026-11-12, about ten weeks later.
- **Different methods.** The market cap is a single day's, with no free-float or liquidity filter. NSE builds its index lists from a 6-month average, so rank and index can disagree even on the same date.
- **No change to any tag.** Under the project's tag rule (CLAUDE.md, "Tags"), membership decides every tag from 2026-04-09 on. These ranks are context only.
- **Not approved data.** These are live Postgres reads, outside `data/APPROVED_DATA.md`. For these stocks, the 2026-09-01 membership rows match the approved D21 copy (`Historical Data/extended_2026-11-12/membership/index_constituents_monthly.csv`). The 2026-11-12 market-cap rows have not been checked against D20.
- **Table built from session output.** The tables above were copied from the output of the session's read-only queries on 2026-11-13. `python -I analysis/basket_band_check.py` reproduces them and writes `stocks.csv`, `summary.csv` and `manifest.json` here. That needs the VPN, because Postgres was unreachable when this file was written. `--check` prints without writing.
