# =============================================================================
# ANALYSIS MASTER BUILDER
# =============================================================================
# Drop this section into weekly_rebalance_nse.py in place of the current
# extract_summary_row() calls and allDf_Index / allDf_Stock / allDf_Combined
# generation blocks.
#
# What changes:
#   REMOVED: extract_summary_row(), allDf_Index/Stock/Combined per-week snapshots
#   ADDED:   build_analysis_master() — one master file per ticker, full history
#
# Output per ticker/index:
#   RSI/Final/Analysis/Master_{label}.xlsx
#   Columns: all 18 W_allRebal columns + SIGN + Long_Weight
#   Rows:    one per weekly rebalance date (full cumulative history)
#   Update:  rebuilt from W_allRebal.xlsx after every Friday run
# =============================================================================

import os
import pandas as pd
import numpy as np


def build_analysis_master(rebal_fp: str, output_fp: str,
                          label: str = '') -> pd.DataFrame | None:
    """
    Build (or refresh) the analysis master file for one index or stock.

    Reads the full W_allRebal.xlsx history, appends two derived columns,
    and writes the master file.  Always a full overwrite — the source of
    truth is W_allRebal, which already carries the incremental history.

    Derived columns added
    ---------------------
    SIGN        : 'SELL' if FUB == ST (price below upper band / downtrend)
                  'BUY'  if FLB == ST (price above lower band / uptrend)

    Long_Weight : composite momentum score used for portfolio weighting
                  = 0.5 × RSI_Close + 0.25 × RSI_High + 0.25 × RSI_Low

    Parameters
    ----------
    rebal_fp  : path to the W_allRebal.xlsx master signal file
    output_fp : destination path for the analysis master Excel file
    label     : ticker / folder name (used only for console output)

    Returns
    -------
    DataFrame with the full history + 2 extra columns, or None on failure.
    """
    if not os.path.exists(rebal_fp):
        print(f"    x  {label or rebal_fp} — W_allRebal not found, skipping")
        return None

    try:
        df = pd.read_excel(rebal_fp)
    except Exception as e:
        print(f"    x  {label} — could not read W_allRebal: {e}")
        return None

    # Drop warm-up rows (no ST computed yet)
    df = df.dropna(subset=['ST']).copy()

    if df.empty:
        print(f"    x  {label} — W_allRebal has no valid rows after dropna")
        return None

    # ── SIGN ─────────────────────────────────────────────────────────────────
    # FUB == ST means price is BELOW the upper band → downtrend → SELL
    # FLB == ST means price is ABOVE the lower band → uptrend  → BUY
    df['SIGN'] = df.apply(
        lambda r: 'SELL' if r['FUB'] == r['ST'] else 'BUY', axis=1
    )

    # ── Long_Weight ───────────────────────────────────────────────────────────
    # Composite RSI score: linear-weighted combination used for portfolio weight
    df['Long_Weight'] = (
        0.5  * df['RSI_Close']
        + 0.25 * df['RSI_High']
        + 0.25 * df['RSI_Low']
    )

    # Write master file
    os.makedirs(os.path.dirname(output_fp), exist_ok=True)
    try:
        df.to_excel(output_fp, index=False)
    except Exception as e:
        print(f"    x  {label} — could not write master: {e}")
        return None

    latest    = df.iloc[-1]
    last_date = pd.to_datetime(latest['Date']).strftime('%Y-%m-%d') \
                if 'Date' in df.columns else 'n/a'
    sign      = latest['SIGN']
    weight    = latest['Long_Weight']

    print(f"  {label:<20}  {len(df):>5} rows  last={last_date}  "
          f"{sign:<4}  LW={weight:.4f}  -> {os.path.basename(output_fp)}")

    return df


# =============================================================================
# REPLACE the index summary section with this block
# (goes after Loop A supertrend runs, where allDf_Index was previously built)
# =============================================================================
def build_all_index_masters(folderName, mainFolderPath, analysisFolderPath, freq):
    """
    Build analysis master files for all active index folders.
    Replaces the allDf_Index + extract_summary_row pattern.
    """
    print("\nBuilding index analysis masters ...")
    masters = {}
    for folder in folderName:
        rebal_fp  = os.path.join(mainFolderPath, folder, f'{freq}_allRebal.xlsx')
        output_fp = os.path.join(analysisFolderPath, f'Master_{folder}.xlsx')
        df = build_analysis_master(rebal_fp, output_fp, label=folder)
        if df is not None:
            masters[folder] = df
    return masters


# =============================================================================
# REPLACE the stock summary section with this block
# (goes after Loop B supertrend runs, where allDf_Stock was previously built)
# =============================================================================
def build_all_stock_masters(stockTickers, stockFolderPath, analysisFolderPath, freq):
    """
    Build analysis master files for all stocks in universe.
    Replaces the allDf_Stock + extract_summary_row pattern.
    """
    print("\nBuilding stock analysis masters ...")
    masters = {}
    for ticker in stockTickers:
        rebal_fp  = os.path.join(stockFolderPath, ticker, f'{freq}_allRebal.xlsx')
        output_fp = os.path.join(analysisFolderPath, f'Master_{ticker}.xlsx')
        df = build_analysis_master(rebal_fp, output_fp, label=ticker)
        if df is not None:
            masters[ticker] = df
    return masters


# =============================================================================
# HOW TO INTEGRATE INTO weekly_rebalance_nse.py
# =============================================================================
# 1. Add this import at the top of the script:
#      from analysis_master import build_all_index_masters, build_all_stock_masters
#
# 2. In Loop A, REPLACE:
#      ── 17h. Index summary (extract_summary_row loop + allDf_Index) ──
#    WITH:
#      index_masters = build_all_index_masters(
#          folderName, mainFolderPath, analysisFolderPath, freq
#      )
#
# 3. In Loop B, REPLACE:
#      extract_summary_row(...) per ticker + allDf_Stock + allDf_Combined
#    WITH:
#      stock_masters = build_all_stock_masters(
#          stockTickers, stockFolderPath, analysisFolderPath, freq
#      )
#
# 4. Remove extract_summary_row(), allDf_Index/Stock/Combined entirely.
#
# Output files produced each Friday run:
#   RSI/Final/Analysis/Master_Nifty100.xlsx
#   RSI/Final/Analysis/Master_MC100.xlsx
#   RSI/Final/Analysis/Master_SC100.xlsx
#   RSI/Final/Analysis/Master_NSEI.xlsx
#   RSI/Final/Analysis/Master_RELIANCE.xlsx
#   RSI/Final/Analysis/Master_TCS.xlsx
#   ... (one per ticker in stock_universe.xlsx)
# =============================================================================
