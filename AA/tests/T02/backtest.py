"""
T02 — EMA-filtered SELL strategy backtest.

Self-contained: reads all data from source files, imports nothing from either
the Wm-SellRegRes or AA analysis code. See T02.md for full data documentation.

Strategy:
    BUY regime  -> hold the full parent basket at rebalance weights (100% equity)
    SELL regime -> keep stocks whose close > 50-day EMA at original weights;
                   allocate excluded stocks' weight to GOLDBEES

No transaction costs in this first pass.

    cd AA/tests/T02
    python backtest.py                     # default paths
    python backtest.py --sellhold <path>   # override Wm-SellRegRes root
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ------------------------------------------------------------------ paths
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]                     # wm-research/AA
EVIDENCE = HERE / "evidence"

SELLHOLD_DEFAULT = Path(r"C:\Users\manur\Repos\Wm-SellRegRes")

# Benchmark files (inside the AA tree)
BENCH_0003_FILE = AA / "Historical Data" / "parent_nav_2026-10-22" / "SCMO_0003.csv"
BENCH_0042_FILE = AA / "Historical Data" / "indices.csv"

# -------------------------------------------------------------- constants
BUY, SELL = "BUY", "SELL"
COL_STRAT = "#2ecc71"
COL_0003 = "#3498db"
COL_0042 = "#e74c3c"
COL_GOLD = "#f1c40f"
COL_SELL_BG = "rgba(255,200,200,0.25)"
_DASH = "\u2014"


# ------------------------------------------------------------------ data
def load_holdings(sellhold: Path) -> pd.DataFrame:
    """Read the weekly holdings table from Wm-SellRegRes outputs."""
    p = sellhold / "outputs" / "weekly" / "all_weeks_holdings.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"Weekly holdings not found at {p}\n"
            f"Run the Wm-SellRegRes pipeline first: cd {sellhold} && python run_all.py")
    df = pd.read_csv(p, parse_dates=["date", "week_end", "run_start"])
    return df.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_ema_signals(sellhold: Path) -> dict[str, dict[pd.Timestamp, int]]:
    """Load per-stock daily 50-day EMA signals.

    Source: SELLHOLD/outputs/stocks_eikon_ema/<TICKER>.csv
    Columns used: date, above_ema50 (string True/False -> 1/0).
    Returns {ticker: {date: 1_or_0}}.
    """
    ema_dir = sellhold / "outputs" / "stocks_eikon_ema"
    out: dict[str, dict[pd.Timestamp, int]] = {}
    if not ema_dir.exists():
        print(f"  WARNING: EMA directory not found at {ema_dir}")
        return out
    for p in sorted(ema_dir.glob("*.csv")):
        ticker = p.stem
        df = pd.read_csv(p, usecols=["date", "above_ema50"], parse_dates=["date"])
        df = df.dropna(subset=["above_ema50"])
        mapped = df["above_ema50"].map(
            {True: 1, "True": 1, False: 0, "False": 0}
        ).astype(int)
        out[ticker] = dict(zip(df["date"], mapped))
    return out


def load_prices(sellhold: Path, tickers: set[str]) -> dict[str, dict[pd.Timestamp, float]]:
    """Load daily close prices for all tickers + GOLDBEES.

    Sources:
        Stocks:  SELLHOLD/outputs/stocks_eikon/<TICKER>.csv  (col: date, close)
        Gold:    SELLHOLD/outputs/gold.csv                    (col: date, close)
    """
    prices: dict[str, dict[pd.Timestamp, float]] = {}
    stock_dir = sellhold / "outputs" / "stocks_eikon"
    loaded, missing = 0, 0
    for t in tickers:
        p = stock_dir / f"{t}.csv"
        if not p.exists():
            missing += 1
            continue
        df = pd.read_csv(p, usecols=["date", "close"], parse_dates=["date"])
        df = df.dropna(subset=["close"])
        prices[t] = dict(zip(df["date"], df["close"]))
        loaded += 1
    print(f"  loaded prices for {loaded} stocks ({missing} missing)")

    gold_file = sellhold / "outputs" / "gold.csv"
    if not gold_file.exists():
        raise FileNotFoundError(f"Gold prices not found at {gold_file}")
    gdf = pd.read_csv(gold_file, parse_dates=["date"]).dropna(subset=["close"])
    prices["GOLD"] = dict(zip(gdf["date"], gdf["close"]))
    print(f"  loaded {len(prices['GOLD'])} gold (GOLDBEES) daily closes")
    return prices


def _nearest_price(lookup: dict, date: pd.Timestamp) -> float | None:
    """Get close on date, or nearest prior within 7 days."""
    if date in lookup:
        return lookup[date]
    for delta in range(1, 8):
        d = date - pd.Timedelta(days=delta)
        if d in lookup:
            return lookup[d]
    return None


def load_benchmarks(start: pd.Timestamp):
    """Load SCMO_0003 and SCMO_0042 NAVs, rebased to 100 at start.

    SCMO_0003: AA/Historical Data/parent_nav_2026-10-22/SCMO_0003.csv
        Columns: _id.scid, _id.date (YYYY/MM/DD), index
        Order: reverse-chronological. Range: 2019-01-03 to 2026-10-22.

    SCMO_0042: AA/Historical Data/indices.csv  (filter scid == SCMO_0042)
        Columns: scid, benchmark, date (DD/MM/YY HH:MM), index, benchmarkIndex
        Range: 2021-11-01 to 2026-08-21.
    """
    # ---- SCMO_0003 ----
    if BENCH_0003_FILE.exists():
        df3 = pd.read_csv(BENCH_0003_FILE)
        df3 = df3.rename(columns={"_id.date": "date", "index": "nav"})
        df3["date"] = pd.to_datetime(df3["date"], format="%Y/%m/%d")
        df3 = df3[["date", "nav"]].sort_values("date").reset_index(drop=True)
        m = df3["date"] >= start
        if m.any():
            base = df3.loc[m, "nav"].iloc[0]
            df3["nav"] = df3["nav"] / base * 100
        df3 = df3[df3["date"] >= start].reset_index(drop=True)
        print(f"  SCMO_0003: {len(df3)} rows, "
              f"{df3['date'].iloc[0].strftime('%Y-%m-%d')} to "
              f"{df3['date'].iloc[-1].strftime('%Y-%m-%d')}")
    else:
        print(f"  WARNING: SCMO_0003 file not found at {BENCH_0003_FILE}")
        df3 = pd.DataFrame(columns=["date", "nav"])

    # ---- SCMO_0042 ----
    if BENCH_0042_FILE.exists():
        df42 = pd.read_csv(BENCH_0042_FILE)
        df42 = df42[df42["scid"] == "SCMO_0042"].copy()
        df42 = df42.rename(columns={"index": "nav"})
        df42["date"] = pd.to_datetime(df42["date"], format="%d/%m/%y %H:%M")
        df42 = df42[["date", "nav"]].sort_values("date").reset_index(drop=True)
        m = df42["date"] >= start
        if m.any():
            base = df42.loc[m, "nav"].iloc[0]
            df42["nav"] = df42["nav"] / base * 100
        df42 = df42[df42["date"] >= start].reset_index(drop=True)
        print(f"  SCMO_0042: {len(df42)} rows, "
              f"{df42['date'].iloc[0].strftime('%Y-%m-%d')} to "
              f"{df42['date'].iloc[-1].strftime('%Y-%m-%d')}")
    else:
        print(f"  WARNING: SCMO_0042 file not found at {BENCH_0042_FILE}")
        df42 = pd.DataFrame(columns=["date", "nav"])

    return df3, df42


# -------------------------------------------------------------- strategy
def build_weekly_targets(holdings: pd.DataFrame, ema: dict) -> list[dict]:
    """Build target portfolio weights for each week.

    BUY regime:  target = {ticker: weight} for all stocks.
    SELL regime: target = {above-EMA stocks: weight, GOLD: residual weight}.
    """
    targets = []
    for date, grp in holdings.groupby("date"):
        regime = grp["portfolio"].iloc[0]
        wts: dict[str, float] = {}
        gold_w = 0.0
        for _, row in grp.iterrows():
            t, w = row["ticker"], row["weight"]
            if pd.isna(w) or w <= 0:
                continue
            if regime == BUY:
                wts[t] = w
            else:
                sig = ema.get(t, {}).get(date, None)
                if sig == 1:
                    wts[t] = w
                else:
                    gold_w += w
        if gold_w > 0:
            wts["GOLD"] = gold_w
        targets.append(dict(
            date=date, regime=regime, targets=wts,
            n_stocks=sum(1 for k in wts if k != "GOLD"),
            gold_weight=gold_w,
        ))
    targets.sort(key=lambda x: x["date"])
    return targets


def run_backtest(targets: list[dict], prices: dict) -> pd.DataFrame:
    """Compute weekly NAV from target weights.

    For each week t, portfolio return = sum(weight_i * return_i) where
    return_i = close(date_{t+1}) / close(date_t) - 1.
    NAV compounds: NAV_{t+1} = NAV_t * (1 + return).
    """
    nav = 100.0
    rows = []
    for i, t in enumerate(targets):
        ret = 0.0
        if i < len(targets) - 1:
            d0, d1 = t["date"], targets[i + 1]["date"]
            for ticker, w in t["targets"].items():
                p0 = _nearest_price(prices.get(ticker, {}), d0)
                p1 = _nearest_price(prices.get(ticker, {}), d1)
                if p0 and p1 and p0 > 0:
                    ret += w * (p1 / p0 - 1)
        rows.append(dict(
            date=t["date"], nav=nav, regime=t["regime"],
            n_stocks=t["n_stocks"], gold_weight=t["gold_weight"],
            return_week=ret,
        ))
        nav *= 1 + ret
    return pd.DataFrame(rows)


# -------------------------------------------------------------- metrics
def compute_metrics(dates, navs, label: str) -> dict:
    """CAGR, max drawdown, volatility, Sharpe (rf=6%), Calmar."""
    s, e = navs.iloc[0], navs.iloc[-1]
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    cagr = (e / s) ** (1 / years) - 1 if years > 0 else 0.0
    rets = navs.pct_change().dropna()
    vol = rets.std() * np.sqrt(52) if len(rets) > 1 else 0.0
    peak = navs.cummax()
    dd = (navs - peak) / peak
    max_dd = dd.min()
    sharpe = (cagr - 0.06) / vol if vol > 0 else np.nan
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan
    return dict(label=label, cagr=cagr, total_return=e / s - 1,
                max_drawdown=max_dd, volatility=vol,
                sharpe=sharpe, calmar=calmar)


# -------------------------------------------------------------- helpers
def _regime_bands(bt: pd.DataFrame):
    """Extract contiguous SELL regime bands for chart shading."""
    bands = []
    in_sell, start = False, None
    for _, row in bt.iterrows():
        if row["regime"] == SELL and not in_sell:
            start = row["date"]
            in_sell = True
        elif row["regime"] != SELL and in_sell:
            bands.append((start, row["date"]))
            in_sell = False
    if in_sell:
        bands.append((start, bt["date"].iloc[-1]))
    return bands


def _snap_benchmark(bench: pd.DataFrame, dates: pd.Series) -> pd.Series:
    """Snap daily benchmark to weekly strategy dates using forward-fill.

    Returns NaN for dates beyond the benchmark's last data point (no
    extrapolation).
    """
    if bench.empty:
        return pd.Series(np.nan, index=dates.index)
    bench = bench.set_index("date").sort_index()
    last_date = bench.index[-1]
    result = []
    for d in dates:
        if d > last_date:
            result.append(np.nan)
        elif d in bench.index:
            result.append(bench.loc[d, "nav"])
        else:
            idx = bench.index.get_indexer([d], method="ffill")
            if idx[0] >= 0:
                result.append(bench.iloc[idx[0]]["nav"])
            else:
                result.append(np.nan)
    return pd.Series(result, index=dates.index)


def _dd_series(navs):
    """Drawdown % series, handling NaN gracefully."""
    valid = navs.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=navs.index)
    peak = valid.cummax()
    return ((valid - peak) / peak * 100).reindex(navs.index)


def _fmt_pct(v):
    if isinstance(v, float) and np.isnan(v):
        return _DASH
    return f"{v * 100:.1f}%"


def _fmt_ratio(v):
    if isinstance(v, float) and np.isnan(v):
        return _DASH
    return f"{v:.2f}"


# -------------------------------------------------------------- report
def build_report(bt, b3_snap, b42_snap, m_strat, m_0003, m_0042, bands):
    """Build self-contained HTML report with Plotly charts."""
    # ---- NAV comparison ----
    fig_nav = go.Figure()
    fig_nav.add_trace(go.Scatter(
        x=bt["date"], y=bt["nav"], name="EMA Strategy",
        line=dict(color=COL_STRAT, width=2)))
    fig_nav.add_trace(go.Scatter(
        x=bt["date"], y=b3_snap, name="SCMO_0003 (Parent)",
        line=dict(color=COL_0003, width=1.5, dash="dot")))
    fig_nav.add_trace(go.Scatter(
        x=bt["date"], y=b42_snap, name="SCMO_0042 (AA)",
        line=dict(color=COL_0042, width=1.5, dash="dash")))
    for s, e in bands:
        fig_nav.add_vrect(x0=s, x1=e, fillcolor=COL_SELL_BG, line_width=0,
                          layer="below")
    fig_nav.update_layout(
        title="NAV Comparison (rebased to 100)",
        xaxis_title="Date", yaxis_title="NAV",
        template="plotly_white", height=450,
        legend=dict(x=0.02, y=0.98))

    # ---- Drawdown ----
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=bt["date"], y=_dd_series(bt["nav"]), name="EMA Strategy",
        line=dict(color=COL_STRAT, width=1.5),
        fill="tozeroy", fillcolor="rgba(46,204,113,0.15)"))
    fig_dd.add_trace(go.Scatter(
        x=bt["date"], y=_dd_series(b3_snap), name="SCMO_0003",
        line=dict(color=COL_0003, width=1, dash="dot")))
    fig_dd.add_trace(go.Scatter(
        x=bt["date"], y=_dd_series(b42_snap), name="SCMO_0042",
        line=dict(color=COL_0042, width=1, dash="dash")))
    fig_dd.update_layout(
        title="Drawdown (%)", xaxis_title="Date", yaxis_title="Drawdown %",
        template="plotly_white", height=350)

    # ---- Gold allocation ----
    fig_gold = go.Figure()
    fig_gold.add_trace(go.Bar(
        x=bt["date"], y=bt["gold_weight"] * 100,
        marker_color=[COL_GOLD if r == SELL else "rgba(200,200,200,0.3)"
                      for r in bt["regime"]],
        name="Gold %"))
    fig_gold.update_layout(
        title="Gold Allocation (% of portfolio weight)",
        xaxis_title="Date", yaxis_title="Weight %",
        template="plotly_white", height=300)

    # ---- Metrics table ----
    all_m = [m_strat, m_0003, m_0042]
    table_rows = ""
    for m in all_m:
        table_rows += (
            f"<tr><td><b>{m['label']}</b></td>"
            f"<td>{_fmt_pct(m['cagr'])}</td>"
            f"<td>{_fmt_pct(m['total_return'])}</td>"
            f"<td>{_fmt_pct(m['max_drawdown'])}</td>"
            f"<td>{_fmt_pct(m['volatility'])}</td>"
            f"<td>{_fmt_ratio(m['sharpe'])}</td>"
            f"<td>{_fmt_ratio(m['calmar'])}</td></tr>\n")

    # ---- Assemble HTML ----
    pjs = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
    nav_div = pio.to_html(fig_nav, full_html=False, include_plotlyjs=False)
    dd_div = pio.to_html(fig_dd, full_html=False, include_plotlyjs=False)
    gold_div = pio.to_html(fig_gold, full_html=False, include_plotlyjs=False)

    start_str = bt["date"].iloc[0].strftime("%Y-%m-%d")
    end_str = bt["date"].iloc[-1].strftime("%Y-%m-%d")
    n_sell = int((bt["regime"] == SELL).sum())
    n_buy = int((bt["regime"] == BUY).sum())
    end_0003 = m_0003.get("end_date", _DASH)
    end_0042 = m_0042.get("end_date", _DASH)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>T02 — EMA Strategy Backtest</title>
{pjs}
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 20px; background: #fafafa; color: #333; }}
h1 {{ font-size: 1.6em; margin-bottom: 0.3em; }}
.sub {{ color: #666; margin-bottom: 1.5em; font-size: 0.95em; }}
.tiles {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
.tile {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
         padding: 16px 20px; min-width: 140px; }}
.tile .v {{ font-size: 1.5em; font-weight: 700; }}
.tile .l {{ font-size: 0.85em; color: #888; margin-top: 4px; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; background: #fff; }}
th, td {{ padding: 10px 14px; text-align: right; border-bottom: 1px solid #eee; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td:first-child, th:first-child {{ text-align: left; }}
.chart {{ margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>T02 {_DASH} EMA-Filtered SELL Strategy Backtest</h1>
<p class="sub">
    <b>Rule:</b> during SELL regime, keep stocks above their 50-day EMA;
    allocate excluded weight to GOLDBEES. During BUY, hold the full parent basket.<br>
    <b>Period:</b> {start_str} to {end_str} ({len(bt)} weeks: {n_buy} BUY, {n_sell} SELL).
    Shaded bands = SELL regime. No transaction costs.
</p>

<div class="tiles">
  <div class="tile">
    <div class="v" style="color:{COL_STRAT}">{_fmt_pct(m_strat['cagr'])}</div>
    <div class="l">Strategy CAGR</div>
  </div>
  <div class="tile">
    <div class="v" style="color:{COL_0003}">{_fmt_pct(m_0003['cagr'])}</div>
    <div class="l">SCMO_0003 CAGR</div>
  </div>
  <div class="tile">
    <div class="v" style="color:{COL_0042}">{_fmt_pct(m_0042['cagr'])}</div>
    <div class="l">SCMO_0042 CAGR</div>
  </div>
  <div class="tile">
    <div class="v">{_fmt_pct(m_strat['max_drawdown'])}</div>
    <div class="l">Strategy Max DD</div>
  </div>
  <div class="tile">
    <div class="v">{_fmt_ratio(m_strat['sharpe'])}</div>
    <div class="l">Strategy Sharpe</div>
  </div>
</div>

<div class="chart">{nav_div}</div>
<div class="chart">{dd_div}</div>

<h2>Performance Metrics</h2>
<table>
<thead><tr>
  <th>Series</th><th>CAGR</th><th>Total Return</th>
  <th>Max Drawdown</th><th>Volatility</th><th>Sharpe</th><th>Calmar</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>

<div class="chart">{gold_div}</div>

<h2>Notes</h2>
<ul>
  <li>No transaction costs applied.</li>
  <li>Returns: point-to-point simple (end/start - 1), compounded weekly.</li>
  <li>Sharpe ratio uses 6% risk-free rate (INR).</li>
  <li>SCMO_0003 data extends to {end_0003};
      SCMO_0042 data extends to {end_0042}.</li>
  <li>Stocks with no EMA data during SELL are excluded (weight goes to gold).</li>
  <li>See T02.md for complete data source documentation and cross-references.</li>
</ul>
</body>
</html>"""


# ------------------------------------------------------------------ run
def run(sellhold: Path):
    print(f"T02 backtest — EMA-filtered SELL strategy")
    print(f"data source: {sellhold}")
    print()

    print("loading holdings ...")
    holdings = load_holdings(sellhold)
    tickers = set(holdings["ticker"].dropna().unique())

    print(f"loading prices for {len(tickers)} stocks + GOLD ...")
    prices = load_prices(sellhold, tickers)

    print("loading EMA signals ...")
    ema = load_ema_signals(sellhold)
    print(f"  {len(ema)} stocks with EMA data")

    print("building weekly targets ...")
    targets = build_weekly_targets(holdings, ema)

    sell_wks = [t for t in targets if t["regime"] == SELL]
    buy_wks = [t for t in targets if t["regime"] == BUY]
    avg_gold = np.mean([t["gold_weight"] for t in sell_wks]) if sell_wks else 0
    avg_n = np.mean([t["n_stocks"] for t in sell_wks]) if sell_wks else 0
    print(f"  {len(targets)} weeks: {len(buy_wks)} BUY, {len(sell_wks)} SELL")
    print(f"  SELL weeks avg: {avg_n:.1f} stocks kept, {avg_gold * 100:.1f}% to gold")

    print("running backtest ...")
    bt = run_backtest(targets, prices)

    start_date = bt["date"].iloc[0]
    print("loading benchmarks ...")
    bench_0003, bench_0042 = load_benchmarks(start_date)

    b3_snap = _snap_benchmark(bench_0003, bt["date"])
    b42_snap = _snap_benchmark(bench_0042, bt["date"])

    m_strat = compute_metrics(bt["date"], bt["nav"], "EMA Strategy")

    mask3 = b3_snap.notna()
    mask42 = b42_snap.notna()

    if mask3.any():
        m_0003 = compute_metrics(
            bt["date"][mask3].reset_index(drop=True),
            b3_snap[mask3].reset_index(drop=True),
            "SCMO_0003 (Parent)")
        m_0003["end_date"] = bt["date"][mask3].iloc[-1].strftime("%Y-%m-%d")
    else:
        m_0003 = dict(label="SCMO_0003 (Parent)", cagr=np.nan,
                      total_return=np.nan, max_drawdown=np.nan,
                      volatility=np.nan, sharpe=np.nan, calmar=np.nan,
                      end_date=_DASH)

    if mask42.any():
        m_0042 = compute_metrics(
            bt["date"][mask42].reset_index(drop=True),
            b42_snap[mask42].reset_index(drop=True),
            "SCMO_0042 (AA)")
        m_0042["end_date"] = bt["date"][mask42].iloc[-1].strftime("%Y-%m-%d")
    else:
        m_0042 = dict(label="SCMO_0042 (AA)", cagr=np.nan,
                      total_return=np.nan, max_drawdown=np.nan,
                      volatility=np.nan, sharpe=np.nan, calmar=np.nan,
                      end_date=_DASH)

    bands = _regime_bands(bt)

    print("building report ...")
    html = build_report(bt, b3_snap, b42_snap, m_strat, m_0003, m_0042, bands)

    EVIDENCE.mkdir(exist_ok=True)
    out_csv = EVIDENCE / "backtest_ema.csv"
    out_html = EVIDENCE / "report.html"

    bt.to_csv(out_csv, index=False, float_format="%.6f")
    out_html.write_text(html, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"EMA Strategy:   NAV {bt['nav'].iloc[-1]:.1f}   "
          f"CAGR {m_strat['cagr'] * 100:.1f}%   "
          f"MaxDD {m_strat['max_drawdown'] * 100:.1f}%   "
          f"Sharpe {m_strat['sharpe']:.2f}")
    if mask3.any():
        print(f"SCMO_0003:      NAV {b3_snap[mask3].iloc[-1]:.1f}   "
              f"CAGR {m_0003['cagr'] * 100:.1f}%   "
              f"MaxDD {m_0003['max_drawdown'] * 100:.1f}%   "
              f"Sharpe {m_0003['sharpe']:.2f}")
    if mask42.any():
        print(f"SCMO_0042:      NAV {b42_snap[mask42].iloc[-1]:.1f}   "
              f"CAGR {m_0042['cagr'] * 100:.1f}%   "
              f"MaxDD {m_0042['max_drawdown'] * 100:.1f}%   "
              f"Sharpe {m_0042['sharpe']:.2f}")
    print(f"{'=' * 60}")
    print(f"written {out_csv}")
    print(f"written {out_html}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="T02: EMA-filtered SELL strategy backtest")
    ap.add_argument("--sellhold", type=Path, default=SELLHOLD_DEFAULT,
                    help="Root of the Wm-SellRegRes project")
    args = ap.parse_args()
    run(args.sellhold)
