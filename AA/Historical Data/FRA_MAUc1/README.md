# FRA_MAUc1: MAUc1 through the Friday job's supertrend

This folder has the same layout as `Friday Rebalance Automation`, for one extra series: **MAUc1**, MCX gold futures (continuous, ₹ per 10 g). It is produced by the desk's own `Python_Scripts/ST.py` and `analysis_master.py`, unmodified.

```
Data/indices_ohlcv.xlsx          sheet MAUc1: date, open, high, low, close, volume
Data/TradingDays.xlsx            copy of production's NSE calendar (to 2026-09-25)
RSI/Final/MAUc1/W_allRebal.xlsx  the permanent signal file (latest Friday)
RSI/Final/MAUc1/W_allRebal_<ddmmyy>.xlsx                    one per production Friday since 2026-07-03
RSI/Final/MAUc1/{indexDf,weekIndexDf,monthIndexDf}_<ddmmyy>_W.xlsx   ST.py's intermediates
RSI/Final/Analysis/Master_MAUc1.xlsx   W_allRebal + SIGN + Long_Weight
run_manifest.json                code hashes, input hash, every run's last signal
```

## How it is made

`AA/analysis/mauc1_st_production.py` does the following:
1. **Copies the production code.** It copies `ST.py`, `QuantBacktester.py`, `ProspectTheory.py` and `analysis_master.py` byte for byte into `AA/analysis/vendor_fra/`, checking sha256 against production. Imports come from those copies, so nothing is written into the production folder.
2. **Loads the data.** It writes the cleaned MAUc1 export (`C:\Users\manur\Downloads\MAUc1_daily1.csv`, via `mauc1_signal.load_clean`) as a sheet of `Data/indices_ohlcv.xlsx`. It then loads the sheet with the job's `_load_index_master` and `_master_to_wide` logic.
3. **Runs ST.py.** It calls `ST.run(scrip, 'W', 2, True, out_d, out_w, out_m, exist, TradingDays.xlsx)`, the same call `weekly_rebalance_nse_v2.py` makes for Nifty 100, Midcap 100 and Smallcap 100. The earlier Fridays use ST.py's own `lastDate` argument.
4. **Builds the Master file.** It runs `analysis_master.build_analysis_master` to build `Master_MAUc1.xlsx`.

**Proof it is the same pipeline.** `python mauc1_st_production.py --repro` re-runs Nifty 100, Midcap 100 and Smallcap 100 from production's `indices_ohlcv.xlsx`. It matches production's 2026-09-25 `W_allRebal.xlsx` in every cell (max difference 0.0) and every SIGN in the Master files.

## Things to know

- **The NSE calendar.** ST.py puts every series on the NSE trading calendar. For MAUc1, that means:
  - the 118 MCX sessions on NSE holidays (2015–2026) are not in the weekly candles;
  - the 3 NSE days without an MCX bar repeat the previous bar.

  The signal is still the same as the earlier review-cut candles in all 603 weeks (`AA/analysis/evidence/final_strategy/mauc1/st_production/`).
- **First signal: week of 2015-03-13.** MAUc1 history starts on 2015-02-02.
- **Partial Friday bars in a live run.** The job runs at about 20:00 IST, but MCX trades until 23:30. A live Friday run would read a partial MAUc1 bar, and the next week's refetch would overwrite it. These files use settled closes.
- **Refreshing.** To refresh, drop a newer MAUc1 export in place, then re-run `python mauc1_st_production.py`. It copies production's current `TradingDays.xlsx` each time.
- **Moving this into production.** To make MAUc1 part of the Friday job itself, add `'MAUc1': 'MAUc1'` to `EIKON_INDEX_RIC_MAP` and `'MAUc1'` to `folderName` and `allFolders` in `weekly_rebalance_nse_v2.py` (the README's "Add a new index" steps). This has not been done.

Latest (week of 2026-09-25): **BUY**. Close 150,881; supertrend line 144,291.4.
