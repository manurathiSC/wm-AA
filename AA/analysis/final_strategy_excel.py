# -*- coding: utf-8 -*-
"""
Build evidence/final_strategy/final_strategy_workbook.xlsx from the CSVs
written by final_strategy.py.

Every step the rule depends on is a live Excel formula:
  Gold_ST        weekly MAUc1 supertrend (true range, weighted ATR, bands,
                 ratchet, trend line, BUY/SELL), rebuilding production ST.py
  Signals_*      weekly decision: all three BUY? -> equity, else sleeve with
                 80/20 or 20/80 from the gold signal read on that review
  D_<book>_*     daily check model: drifting equity / gold / cash values,
                 trades only when the target changes, 10.4 bps one-way cost,
                 NAV, drawdown; alongside the harness NAV for comparison
  Summary        stats, and the check model against the harness
Parameters (weights, costs, supertrend multiplier) sit on Params.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from common import EVIDENCE_DIR, PAIRS

E = EVIDENCE_DIR / "final_strategy"
XL = E / "final_strategy_workbook.xlsx"
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="E8ECF2")
INPUT = PatternFill("solid", fgColor="FFF6DD")
PCT, DATE, NUM = "0.00%", "yyyy-mm-dd", "0.000000"
FINAL = "FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)"
PERIODS = {"live": "live 2021-11 -> 2026-08", "1421": "before the books 2014-07 -> 2021-10"}
FILE_TAG = {"live": "live", "1421": "2014_2021"}


def d(x):
    return pd.Timestamp(x).to_pydatetime().replace(tzinfo=None) if pd.notna(x) else None


def header(ws, cols, row=1, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.font, cell.fill = BOLD, HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(j, 13)
    ws.freeze_panes = ws.cell(row=row + 1, column=2)


def params(wb):
    ws = wb.create_sheet("Params")
    rows = [("Round-trip cost per full switch (bps)", 20.8, "Harness PRIMARY_BPS. Half is charged on each side of a trade."),
            ("One-way cost (fraction)", "=B2/2/10000", "Applied to the value traded at each rebalance."),
            ("Sleeve gold share when gold signal = BUY", 0.8, "Rule 2.1: 80% gold / 20% cash."),
            ("Sleeve gold share when gold signal = SELL", 0.2, "Rule 2.2: 20% gold / 80% cash."),
            ("Sleeve gold share if no gold signal yet", 0.5, "Before MAUc1's first ST.py signal (2015-03-13), so the 2014-15 sleeve weeks hold 50/50."),
            ("Gold supertrend multiplier", 2, "Production supertrend: bands = (H+L)/2 +/- multiplier x weighted ATR."),
            ("Gold supertrend ATR bars (weights 1..5)", 5, "Linearly weighted mean of the last 5 weekly true ranges (weights 1,2,3,4,5 / 15). The weights are written into Gold_ST!L."),
            ("GOLDBEES de-spike tolerance on top of MCX gold's day range", 0.005, "GOLDBEES_fill: open/high/low are pulled into close x (1 +/- (MCX range + this)).")]
    header(ws, ["Parameter", "Value", "Note"], widths={1: 44, 2: 12, 3: 90})
    for i, (a, b, c) in enumerate(rows, 2):
        ws.cell(row=i, column=1, value=a)
        v = ws.cell(row=i, column=2, value=b)
        v.fill = INPUT
        ws.cell(row=i, column=3, value=c)
    ws.freeze_panes = None
    return ws


def gold_sheets(wb):
    """MAUc1 daily bars as ST.py saw them, the MAUc1 weekly supertrend (ST.py candles), and the GOLDBEES fill."""
    g = pd.read_csv(E / "gold_supertrend_weekly.csv", parse_dates=["review", "last_session"])
    gd = pd.read_csv(E / "gold_signal_daily_mauc1.csv", parse_dates=["date", "candle_review"])
    wd = wb.create_sheet("Gold_daily")
    header(wd, ["date (NSE trading day)", "open (MCX)", "high", "low", "close", "candle it belongs to (week label = review)",
                "real MCX session? (no = previous bar repeated)"], widths={1: 14, 6: 24, 7: 22})
    for i, r in enumerate(gd.itertuples(), 2):
        wd.cell(row=i, column=1, value=d(r.date)).number_format = DATE
        for j, v in enumerate((r.open, r.high, r.low, r.close), 2):
            wd.cell(row=i, column=j, value=None if pd.isna(v) else float(v))
        wd.cell(row=i, column=6, value=d(r.candle_review)).number_format = DATE
        wd.cell(row=i, column=7, value="yes" if r.mcx_session else "no")
    ws = wb.create_sheet("Gold_ST")
    cols = ["candle = review date", "last NSE session in candle", "high", "low", "close", "prev close", "H-L", "|H-prev C|", "|L-prev C|",
            "true range", "(H+L)/2", "weighted ATR (5)", "basic upper", "basic lower", "final upper", "final lower", "supertrend",
            "SIGNAL (1 BUY / 0 SELL)", "ST.py SIGN (Master_MAUc1)", "check", "check: high = MAXIFS(daily)", "check: low = MINIFS(daily)"]
    header(ws, cols, widths={1: 13, 2: 13, 18: 12, 21: 14, 22: 14})
    first = 7                                   # 6th candle -> first weighted ATR (ST.py rebalStartIndex = 5)
    for k, r in enumerate(g.itertuples()):
        i = k + 2
        ws.cell(row=i, column=1, value=d(r.review)).number_format = DATE
        ws.cell(row=i, column=2, value=d(r.last_session)).number_format = DATE
        ws.cell(row=i, column=3, value=float(r.high))
        ws.cell(row=i, column=4, value=float(r.low))
        ws.cell(row=i, column=5, value=float(r.close))
        if i > 2:
            ws.cell(row=i, column=6, value=f"=E{i-1}")
            ws.cell(row=i, column=8, value=f"=ABS(C{i}-F{i})")
            ws.cell(row=i, column=9, value=f"=ABS(D{i}-F{i})")
            ws.cell(row=i, column=10, value=f"=MAX(G{i},H{i},I{i})")
        else:
            ws.cell(row=i, column=10, value=f"=G{i}")
        ws.cell(row=i, column=7, value=f"=C{i}-D{i}")
        ws.cell(row=i, column=11, value=f"=(C{i}+D{i})/2")
        if i >= first:
            ws.cell(row=i, column=12, value=f"=(1*J{i-4}+2*J{i-3}+3*J{i-2}+4*J{i-1}+5*J{i})/15")
            ws.cell(row=i, column=13, value=f"=K{i}+Params!$B$7*L{i}")
            ws.cell(row=i, column=14, value=f"=K{i}-Params!$B$7*L{i}")
            if i == first:
                ws.cell(row=i, column=15, value=f"=M{i}")
                ws.cell(row=i, column=16, value=f"=N{i}")
                ws.cell(row=i, column=17, value=f"=O{i}")
            else:
                ws.cell(row=i, column=15, value=f"=IF(OR(M{i}<O{i-1},F{i}>O{i-1}),M{i},O{i-1})")
                ws.cell(row=i, column=16, value=f"=IF(OR(N{i}>P{i-1},F{i}<P{i-1}),N{i},P{i-1})")
                ws.cell(row=i, column=17, value=(f"=IF(AND(Q{i-1}=O{i-1},E{i}<=O{i}),O{i},IF(AND(Q{i-1}=O{i-1},E{i}>O{i}),P{i},"
                                                 f"IF(AND(Q{i-1}=P{i-1},E{i}>=P{i}),P{i},IF(AND(Q{i-1}=P{i-1},E{i}<O{i}),O{i},0))))"))
            ws.cell(row=i, column=18, value=f'=IF(ABS(Q{i}-P{i})<0.000000001,1,IF(ABS(Q{i}-O{i})<0.000000001,0,""))')
        else:
            # warm-up candles have no signal yet: an explicit blank, so a review reading one falls back to 50/50
            ws.cell(row=i, column=18, value='=""')
        ws.cell(row=i, column=19, value=None if pd.isna(r.signal) else float(r.signal))
        ws.cell(row=i, column=20, value=f'=IF(S{i}="","",IF(R{i}=S{i},"ok","DIFF"))')
        ws.cell(row=i, column=21, value=f'=IF(MAXIFS(Gold_daily!$C:$C,Gold_daily!$F:$F,A{i})=C{i},"ok","DIFF")')
        ws.cell(row=i, column=22, value=f'=IF(MINIFS(Gold_daily!$D:$D,Gold_daily!$F:$F,A{i})=D{i},"ok","DIFF")')
    # GOLDBEES fill: OHLC4 after pulling open/high/low into close +/- (MCX range + tolerance)
    f = pd.read_csv(E / "goldbees_fill_despiked.csv", index_col=0, parse_dates=True)
    wf = wb.create_sheet("GOLDBEES_fill")
    header(wf, ["date", "open", "high", "low", "close", "MCX gold range that day (H-L)/C", "band = range + tolerance", "lower limit", "upper limit",
                "open (clean)", "high (clean)", "low (clean)", "OHLC4 raw", "FILL = OHLC4 clean", "python fill", "check"], widths={6: 16, 7: 14})
    for k, r in enumerate(f.itertuples()):
        i = k + 2
        wf.cell(row=i, column=1, value=d(r.Index)).number_format = DATE
        for j, v in enumerate((r.open, r.high, r.low, r.close), 2):
            wf.cell(row=i, column=j, value=float(v))
        if pd.notna(r.mcx_range):
            wf.cell(row=i, column=6, value=float(r.mcx_range))
        wf.cell(row=i, column=7, value=f'=IF(F{i}="","",F{i}+Params!$B$9)')
        wf.cell(row=i, column=8, value=f'=IF(G{i}="","",E{i}*(1-G{i}))')
        wf.cell(row=i, column=9, value=f'=IF(G{i}="","",E{i}*(1+G{i}))')
        wf.cell(row=i, column=10, value=f'=IF(G{i}="",B{i},MIN(MAX(B{i},H{i}),I{i}))')
        wf.cell(row=i, column=11, value=f'=MAX(IF(G{i}="",C{i},MIN(C{i},I{i})),J{i},E{i})')
        wf.cell(row=i, column=12, value=f'=MIN(IF(G{i}="",D{i},MAX(D{i},H{i})),J{i},E{i})')
        wf.cell(row=i, column=13, value=f"=(B{i}+C{i}+D{i}+E{i})/4")
        wf.cell(row=i, column=14, value=f"=(J{i}+K{i}+L{i}+E{i})/4")
        wf.cell(row=i, column=15, value=float(r.fill_ohlc4_clean))
        wf.cell(row=i, column=16, value=f'=IF(ABS(N{i}-O{i})<0.0000001,"ok","DIFF")')
        for c in (6, 7):
            wf.cell(row=i, column=c).number_format = "0.00%"
    return len(g) + 1


def signals_sheet(wb, key):
    w = pd.read_csv(E / f"weekly_signals_{FILE_TAG[key]}.csv", parse_dates=["review", "entry_session"])
    ws = wb.create_sheet(f"Signals_{key}")
    cols = ["review (Friday close)", "trade session (Monday, OHLC4 fill)", "N100 SIGN", "MC100 SIGN", "SC100 SIGN", "all three BUY?",
            "decision", "gold signal on review (1 BUY / 0 SELL)", "equity weight", "gold share of sleeve", "gold weight", "cash weight",
            "variant: gold share fixed at sleeve entry", "variant gold weight", "variant cash weight", "python gold weight", "check",
            "python gold signal (MAUc1)", "previous signal (GOLDBEES)"]
    header(ws, cols, widths={2: 14, 8: 16, 13: 16})
    for k, r in enumerate(w.itertuples()):
        i = k + 2
        ws.cell(row=i, column=1, value=d(r.review)).number_format = DATE
        ws.cell(row=i, column=2, value=d(r.entry_session)).number_format = DATE
        ws.cell(row=i, column=3, value=r.N100)
        ws.cell(row=i, column=4, value=r.MC100)
        ws.cell(row=i, column=5, value=r.SC100)
        ws.cell(row=i, column=6, value=f'=AND(C{i}="BUY",D{i}="BUY",E{i}="BUY")')
        ws.cell(row=i, column=7, value=f'=IF(F{i},"EQUITY","SLEEVE")')
        ws.cell(row=i, column=8, value=f'=IFERROR(INDEX(Gold_ST!$R:$R,MATCH(A{i},Gold_ST!$A:$A,1)),"")')
        ws.cell(row=i, column=9, value=f'=IF(G{i}="EQUITY",1,0)')
        ws.cell(row=i, column=10, value=f'=IF(H{i}="",Params!$B$6,IF(H{i}=1,Params!$B$4,Params!$B$5))')
        ws.cell(row=i, column=11, value=f"=(1-I{i})*J{i}")
        ws.cell(row=i, column=12, value=f"=(1-I{i})*(1-J{i})")
        if i == 2:
            ws.cell(row=i, column=13, value=f"=J{i}")
        else:
            ws.cell(row=i, column=13, value=f'=IF(G{i}="EQUITY",J{i},IF(G{i-1}="EQUITY",J{i},M{i-1}))')
        ws.cell(row=i, column=14, value=f"=(1-I{i})*M{i}")
        ws.cell(row=i, column=15, value=f"=(1-I{i})*(1-M{i})")
        ws.cell(row=i, column=16, value=float(r.gold_w))
        ws.cell(row=i, column=17, value=f'=IF(ABS(K{i}-P{i})<0.000000001,"ok","DIFF")')
        ws.cell(row=i, column=18, value=None if pd.isna(r.gold_signal) else float(r.gold_signal))
        gg = getattr(r, "gold_signal_goldbees", np.nan)
        ws.cell(row=i, column=19, value=None if pd.isna(gg) else float(gg))
        for c in (10, 11, 12, 13, 14, 15, 16):
            ws.cell(row=i, column=c).number_format = "0%"
    return w, len(w) + 1


def daily_sheet(wb, key, aa, w, nsig):
    df = pd.read_csv(E / f"daily_{aa}_{FILE_TAG[key]}.csv", index_col=0, parse_dates=True)
    # the review executed at each session (a later review wins a shared entry, as in the harness)
    ex = {}
    for r in w.itertuples():
        ex[pd.Timestamp(r.entry_session)] = pd.Timestamp(r.review)
    first = min(ex)
    df = df.loc[first:]
    pub = None
    if key == "live":
        C = pd.read_csv(E / "nav_curves_daily.csv", index_col=0, parse_dates=True)
        pub = {nm: C.get(f"{PERIODS[key]}|{aa}|{nm}") for nm in ("published parent NAV", "published AA NAV (as traded)")}
    ws = wb.create_sheet(f"D_{aa[-4:]}_{key}")
    cols = ["date", "review executed today (Monday trade)", "gold fill price (OHLC4)", "gold close", "cash level",
            "parent value at fill prices (OHLC4)", "parent value at close", "target equity w", "target gold w", "target cash w",
            "trade today? (1/0)", "equity value at fill", "gold value at fill", "cash value at fill", "NAV at fill", "value traded",
            "cost", "equity after trade", "gold after trade", "cash after trade", "equity at close", "gold at close", "cash at close",
            "NAV (check model)", "NAV (harness)", "check − harness", "running max", "drawdown", "published parent NAV", "published AA NAV"]
    header(ws, cols, widths={2: 14, 6: 14, 7: 14, 24: 14, 25: 14})
    S = f"Signals_{key}"
    for k, r in enumerate(df.itertuples()):
        i = k + 2
        t = r.Index
        ws.cell(row=i, column=1, value=d(t)).number_format = DATE
        rv = ex.get(t)
        if rv is not None:
            ws.cell(row=i, column=2, value=d(rv)).number_format = DATE
        ws.cell(row=i, column=3, value=float(r.gold_fill_ohlc4))
        ws.cell(row=i, column=4, value=float(r.gold_price))
        ws.cell(row=i, column=5, value=float(r.cash_level))
        ws.cell(row=i, column=6, value=float(r.parent_fill_nav))
        ws.cell(row=i, column=7, value=float(r.parent_harness_nav))
        if i == 2:
            for c, col in ((8, "I"), (9, "K"), (10, "L")):
                ws.cell(row=i, column=c, value=f"=INDEX({S}!${col}$2:${col}${nsig},MATCH(B{i},{S}!$A$2:$A${nsig},0))")
            ws.cell(row=i, column=11, value=1)
            for c in (12, 13, 14):
                ws.cell(row=i, column=c, value=0)
            ws.cell(row=i, column=15, value=1)
        else:
            for c, col, prev in ((8, "I", "H"), (9, "K", "I"), (10, "L", "J")):
                ws.cell(row=i, column=c, value=f'=IF(B{i}="",{prev}{i-1},INDEX({S}!${col}$2:${col}${nsig},MATCH(B{i},{S}!$A$2:$A${nsig},0)))')
            ws.cell(row=i, column=11, value=f'=IF(AND(B{i}<>"",OR(ABS(H{i}-H{i-1})>0.000000001,ABS(I{i}-I{i-1})>0.000000001)),1,0)')
            ws.cell(row=i, column=12, value=f"=U{i-1}*F{i}/G{i-1}")
            ws.cell(row=i, column=13, value=f"=V{i-1}*C{i}/D{i-1}")
            ws.cell(row=i, column=14, value=f"=W{i-1}*E{i}/E{i-1}")
            ws.cell(row=i, column=15, value=f"=L{i}+M{i}+N{i}")
        ws.cell(row=i, column=16, value=f"=IF(K{i}=1,ABS(O{i}*H{i}-L{i})+ABS(O{i}*I{i}-M{i})+ABS(O{i}*J{i}-N{i}),0)")
        ws.cell(row=i, column=17, value=f"=P{i}*Params!$B$3")
        ws.cell(row=i, column=18, value=f"=IF(K{i}=1,(O{i}-Q{i})*H{i},L{i})")
        ws.cell(row=i, column=19, value=f"=IF(K{i}=1,(O{i}-Q{i})*I{i},M{i})")
        ws.cell(row=i, column=20, value=f"=IF(K{i}=1,(O{i}-Q{i})*J{i},N{i})")
        ws.cell(row=i, column=21, value=f"=R{i}*G{i}/F{i}")
        ws.cell(row=i, column=22, value=f"=S{i}*D{i}/C{i}")
        ws.cell(row=i, column=23, value=f"=T{i}")
        ws.cell(row=i, column=24, value=f"=U{i}+V{i}+W{i}")
        ws.cell(row=i, column=25, value=float(r.harness_nav))
        ws.cell(row=i, column=26, value=f"=X{i}-Y{i}")
        ws.cell(row=i, column=27, value=f"=X{i}" if i == 2 else f"=MAX(AA{i-1},X{i})")
        ws.cell(row=i, column=28, value=f"=X{i}/AA{i}-1")
        if pub:
            for c, nm in ((29, "published parent NAV"), (30, "published AA NAV (as traded)")):
                s_ = pub[nm]
                if s_ is not None and pd.notna(s_.get(t, np.nan)):
                    ws.cell(row=i, column=c, value=float(s_[t]))
        for c in (8, 9, 10):
            ws.cell(row=i, column=c).number_format = "0%"
        ws.cell(row=i, column=28).number_format = "0.000%"
    return ws.title, len(df) + 1, df


def table_sheet(wb, name, df, pct_cols=(), date_cols=(), widths=None):
    ws = wb.create_sheet(name)
    header(ws, list(df.columns), widths=widths)
    for i, row in enumerate(df.itertuples(index=False), 2):
        for j, v in enumerate(row, 1):
            if isinstance(v, (float, np.floating)) and np.isnan(v):
                v = None
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            elif isinstance(v, pd.Timestamp):
                v = d(v)
            c = ws.cell(row=i, column=j, value=v)
            col = df.columns[j - 1]
            if col in pct_cols:
                c.number_format = PCT
            if col in date_cols:
                c.number_format = DATE
    return ws


def spells(key):
    w = pd.read_csv(E / f"weekly_signals_{FILE_TAG[key]}.csv", parse_dates=["review", "entry_session"])
    df = pd.read_csv(E / f"daily_SCMO_0042_{FILE_TAG[key]}.csv", index_col=0, parse_dates=True)
    w["blk"] = (w.decision != w.decision.shift()).cumsum()
    out = []
    for _, g in w[w.decision == "SLEEVE"].groupby("blk"):
        nxt = w[w.review > g.review.iloc[-1]].head(1)
        a = g.entry_session.iloc[0]
        b = nxt.entry_session.iloc[0] if len(nxt) else df.index[-1]
        seg = df.loc[a:b]
        rg = seg.gold_price.iloc[-1] / seg.gold_price.iloc[0] - 1
        rc = seg.cash_level.iloc[-1] / seg.cash_level.iloc[0] - 1
        out.append({"period": PERIODS[key], "first sleeve review": g.review.iloc[0].date(), "sleeve entered at close of": a.date(),
                    "back to equity at close of": b.date() if len(nxt) else "still in sleeve at end",
                    "weeks": round((b - a).days / 7, 1), "gold signal at entry": g.gold_signal.iloc[0],
                    "gold share at entry": g.gold_w.iloc[0], "gold-signal flips inside the spell": int((g.gold_signal.diff().abs() > 0).sum()),
                    "gold return": rg, "cash return": rc, "80/20 held throughout": 0.8 * rg + 0.2 * rc, "20/80 held throughout": 0.2 * rg + 0.8 * rc,
                    "50/50 held throughout": 0.5 * rg + 0.5 * rc,
                    "sleeve return, final rule (book 0042 harness NAV)": seg.harness_nav.iloc[-1] / seg.harness_nav.iloc[0] - 1,
                    **{f"parent {aa[-4:]} return": np.nan for aa in PAIRS}})
        for aa in PAIRS:
            dd = pd.read_csv(E / f"daily_{aa}_{FILE_TAG[key]}.csv", index_col=0, parse_dates=True).loc[a:b]
            out[-1][f"parent {aa[-4:]} return"] = dd.parent_harness_nav.iloc[-1] / dd.parent_harness_nav.iloc[0] - 1
    return pd.DataFrame(out)


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    summ = pd.read_csv(E / "summary_stats.csv")
    params(wb)
    ngold = gold_sheets(wb)
    sig = {}
    for key in ("live", "1421"):
        sig[key] = signals_sheet(wb, key)
    dsheets = []
    for key in ("live", "1421"):
        for aa in PAIRS:
            dsheets.append((key, aa) + daily_sheet(wb, key, aa, sig[key][0], sig[key][1]))

    # ── Summary ─────────────────────────────────────────────────────────────
    sm = wb.create_sheet("Summary", 1)
    avg = (summ.groupby(["period", "strategy"], sort=False)[["cagr", "vol", "max_dd_daily", "max_dd_friday", "calmar", "sharpe_vs_cash",
                                                            "avg_equity_weight", "switches_equity_sleeve", "sleeve_resplits"]].mean().reset_index())
    r0 = 1
    sm.cell(row=r0, column=1, value="A. Average of the four portfolios (harness)").font = Font(bold=True, size=12)
    cols = ["period", "strategy", "CAGR", "volatility", "worst fall (daily)", "worst fall (Friday)", "Calmar", "Sharpe vs cash",
            "avg equity weight", "equity<->sleeve switches", "sleeve re-splits"]
    header(sm, cols, row=r0 + 1, widths={1: 34, 2: 58})
    for i, rr in enumerate(avg.itertuples(index=False), r0 + 2):
        for j, v in enumerate(rr, 1):
            c = sm.cell(row=i, column=j, value=(None if isinstance(v, float) and np.isnan(v) else v))
            if j in (3, 4, 5, 6, 9):
                c.number_format = PCT
            elif j in (7, 8):
                c.number_format = "0.00"
            if isinstance(rr[1], str) and rr[1].startswith("FINAL"):
                c.font = BOLD
    r1 = r0 + 3 + len(avg) + 1
    sm.cell(row=r1, column=1, value="B. Check model (formulas on the D_ sheets) against the harness, same rows").font = Font(bold=True, size=12)
    cols = ["period", "portfolio", "sheet", "first row", "last row", "check-model CAGR", "harness CAGR (same rows)", "difference (pp/yr)",
            "check-model worst fall", "harness worst fall (same rows)", "check-model final NAV", "harness final NAV"]
    for j, c in enumerate(cols, 1):
        cell = sm.cell(row=r1 + 1, column=j, value=c)
        cell.font, cell.fill = BOLD, HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for k, (key, aa, title, last, df) in enumerate(dsheets):
        i = r1 + 2 + k
        sm.cell(row=i, column=1, value=PERIODS[key])
        sm.cell(row=i, column=2, value=aa)
        sm.cell(row=i, column=3, value=title)
        sm.cell(row=i, column=4, value=f"='{title}'!A2").number_format = DATE
        sm.cell(row=i, column=5, value=f"='{title}'!A{last}").number_format = DATE
        sm.cell(row=i, column=6, value=f"=('{title}'!X{last}/'{title}'!X2)^(365.25/('{title}'!A{last}-'{title}'!A2))-1").number_format = PCT
        sm.cell(row=i, column=7, value=f"=('{title}'!Y{last}/'{title}'!Y2)^(365.25/('{title}'!A{last}-'{title}'!A2))-1").number_format = PCT
        sm.cell(row=i, column=8, value=f"=(F{i}-G{i})*100").number_format = "0.00"
        sm.cell(row=i, column=9, value=f"=MIN('{title}'!AB2:AB{last})").number_format = PCT
        sm.cell(row=i, column=10, value=float((df.harness_nav / df.harness_nav.cummax() - 1).min())).number_format = PCT
        sm.cell(row=i, column=11, value=f"='{title}'!X{last}").number_format = "0.0000"
        sm.cell(row=i, column=12, value=f"='{title}'!Y{last}").number_format = "0.0000"
    r2 = r1 + 3 + len(dsheets) + 1
    ga = E / "check_model_gap_attribution.csv"
    if ga.exists():
        g = pd.read_csv(ga)
        sm.cell(row=r2, column=1, value="C. Where the check model and the harness differ (log-points a year, check − harness)").font = Font(bold=True, size=12)
        cols = ["period", "portfolio", "total", "inside sleeve spells", "day moved into sleeve", "inside equity spells", "day moved back to equity"]
        for j, c in enumerate(cols, 1):
            cell = sm.cell(row=r2 + 1, column=j, value=c)
            cell.font, cell.fill = BOLD, HEAD
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for k, rr in enumerate(g.itertuples(index=False)):
            row =[PERIODS[rr.period], rr.aa, float(rr.total), float(g.iloc[k]["inside sleeve"]), float(g.iloc[k]["day moved into sleeve"]),
                   float(g.iloc[k]["inside equity"]), float(g.iloc[k]["day moved back to equity"])]
            for j, v in enumerate(row, 1):
                c = sm.cell(row=r2 + 2 + k, column=j, value=v)
                if j >= 3:
                    c.number_format = "0.000"
        note = ("Inside sleeve spells, and on the days the book returns to equity, the check model and the harness agree exactly (0.000): the gold/cash drift, the 80/20 <-> 20/80 re-splits and the costs reconcile. "
                "The gap comes from two harness conventions a spreadsheet cannot copy without stock-level prices: (1) on the day the book moves into the sleeve the harness sells the stocks at that session's OHLC4, the check model at the close; "
                "(2) inside equity spells the harness holds the parent's current basket bought at its published weights at each re-entry, while the check model follows the parent's own drifted NAV.")
        c = sm.cell(row=r2 + 3 + len(g), column=1, value=note)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        sm.merge_cells(start_row=r2 + 3 + len(g), start_column=1, end_row=r2 + 3 + len(g), end_column=8)
        sm.row_dimensions[r2 + 3 + len(g)].height = 75
        r2 = r2 + 5 + len(g)
    vf = E / "verification.csv"
    if vf.exists():
        v = pd.read_csv(vf)
        sm.cell(row=r2, column=1, value="D. Formula verification (pycel, an independent Excel formula engine)").font = Font(bold=True, size=12)
        for j, c in enumerate(["check", "rows", "mismatches"], 1):
            cell = sm.cell(row=r2 + 1, column=j, value=c)
            cell.font, cell.fill = BOLD, HEAD
        for k, rr in enumerate(v.itertuples(index=False)):
            sm.cell(row=r2 + 2 + k, column=1, value=rr.check)
            sm.cell(row=r2 + 2 + k, column=2, value=int(rr.rows))
            sm.cell(row=r2 + 2 + k, column=3, value=int(rr.mismatches))
        rp = E / "check_model_reconciliation.csv"
        extra = ""
        if rp.exists():
            extra = " Daily NAV of every D_ sheet, evaluated formula by formula, equals the Python replica of the same recursion to within 1e-13."
        sm.cell(row=r2 + 3 + len(v), column=1, value="All formula outputs were evaluated with pycel and compared with the Python engine." + extra)
        r2 = r2 + 5 + len(v)
    sm.cell(row=r2, column=1, value="E. Every portfolio and strategy (harness) — full table on sheet Stats_all").font = Font(bold=True, size=12)

    table_sheet(wb, "Stats_all", summ, pct_cols={"cagr", "vol", "max_dd_daily", "max_dd_friday", "total_return", "avg_equity_weight",
                                                 "cost_paid_share_of_nav"}, widths={1: 34, 4: 58})
    yr = pd.read_csv(E / "yearly_returns.csv")
    table_sheet(wb, "Yearly", yr, pct_cols=set(yr.columns[1:]), widths={1: 90})
    tl = pd.read_csv(E / "trade_log.csv", parse_dates=["entry", "review"])
    tl = tl[tl.strategy == FINAL]
    table_sheet(wb, "Trades_final", tl[["period", "aa", "review", "entry", "kind", "sleeve_weight", "gold_share_of_sleeve", "turnover_frac",
                                        "cost", "nav", "n_target", "n_filled"]],
                pct_cols={"sleeve_weight", "gold_share_of_sleeve", "turnover_frac"}, date_cols={"review", "entry"}, widths={1: 32})
    pl = pd.read_csv(E / "position_log.csv", parse_dates=["entry", "review"])
    pl = pl[pl.strategy == FINAL]
    table_sheet(wb, "Positions_final", pl[["period", "aa", "review", "entry", "ticker", "name", "key", "w_before", "w_after", "fill_price"]],
                pct_cols={"w_before", "w_after"}, date_cols={"review", "entry"}, widths={1: 32, 6: 30})
    sp = pd.concat([spells("live"), spells("1421")], ignore_index=True)
    sp.to_csv(E / "sleeve_spells.csv", index=False)
    table_sheet(wb, "Sleeve_spells", sp, pct_cols={c for c in sp.columns if "return" in c or "held" in c or c == "gold share at entry"}, widths={1: 32})

    # ── README ──────────────────────────────────────────────────────────────
    lines = [
        ("Final strategy test — all four AA portfolios", True),
        ("", False),
        ("THE RULE", True),
        ("1. Each Friday review: if Nifty 100, Nifty Midcap 100 and Nifty Smallcap 100 are all BUY (production weekly supertrend), hold the whole parent portfolio.", False),
        ("2. Otherwise hold the alternate sleeve of gold (GOLDBEES) and cash (LBES). The split follows gold's weekly supertrend computed on MAUc1 (MCX gold futures, continuous):", False),
        ("   2.1 MAUc1 supertrend BUY  -> 80% GOLDBEES / 20% cash", False),
        ("   2.2 MAUc1 supertrend SELL -> 20% GOLDBEES / 80% cash", False),
        ("   Before MAUc1's first signal (2015-03-05) a sleeve week holds 50/50 (two spells in 2014-15).", False),
        ("   The gold/cash split matters only while the book is in the sleeve. It is re-checked at every weekly review while in the sleeve (FINAL). The variant fixes the split at the review that moves the book into the sleeve.", False),
        ("3. Every signal is known at Friday's close, from that week's weekly candle. The trade is taken on the next session (Monday; Tuesday when Monday is a holiday) at that session's OHLC average, (open+high+low+close)/4, for every stock and for GOLDBEES. Cash (LBES) trades at its daily level. When Friday is a holiday the week's candle, and so the signal, closes on Thursday. Nothing trades while the target is unchanged, so weights drift between trades. Cost is 20.8 bps round trip (10.4 bps on each side of every trade).", False),
        ("", False),
        ("PERIODS", True),
        ("live 2021-11 -> 2026-08: the four AA books (SCMO_0042-0045) on their parents' baskets. Published parent and AA NAVs are shown for reference.", False),
        ("before the books 2014-07 -> 2021-10: the same four parents' real baskets (Eikon prices), before the AA books existed.", False),
        ("Caveat: the three-index rule and the 80/20 idea were both formed after looking at 2014-2026 data, so neither period is a clean out-of-sample test of this exact combination.", False),
        ("", False),
        ("SHEETS", True),
        ("Summary: A = average of the four portfolios for every strategy; B = the formula check model against the harness.", False),
        ("Stats_all: every portfolio x strategy x period (CAGR, volatility, worst fall daily and Friday, Calmar, Sharpe vs cash, time in equity, switches, re-splits, cost).", False),
        ("Yearly: calendar-year returns of every series.", False),
        ("Params: editable inputs (yellow). Changing them recalculates the Gold_ST, Signals and D_ sheets. The harness columns stay as run.", False),
("Gold_daily: MAUc1 daily bars exactly as production ST.py saw them (its indexDf): the user's Eikon export (cleaned; see mauc1/mauc1_cleaning_log.csv) put on the NSE trading calendar, so an MCX session on an NSE holiday is not there and an NSE day with no MCX bar repeats the previous bar (column G). Gold_ST: one candle per NSE week (max high, min low, last close), labelled by its last NSE session, which is the review, and the supertrend on those candles, all as formulas. The first trend value is on the 6th candle, as in ST.py. 'ST.py SIGN' is the value in Historical Data/FRA_MAUc1/RSI/Final/Analysis/Master_MAUc1.xlsx, from the desk's ST.py run unmodified (mauc1_st_production.py); 'check' compares.", False),
        ("GOLDBEES_fill: the price the book pays for GOLDBEES on a trade session: OHLC4 after pulling open, high and low into close x (1 +/- (MCX gold's high-low range that day + 0.5%)). This strips ETF-only spikes, such as the 22% intraday low on 2026-03-04. Column C of each D_ sheet uses it.", False),
        ("Signals_live / Signals_1421: one row per weekly review. The three index signs are from the production Master_*.xlsx files. The decision, gold signal lookup, weights and variant are formulas.", False),
        ("D_<book>_<period>: the daily check model. Every holding is first carried from the previous close to today's fill price: the parent at its value at OHLC4 prices (column F), gold at its OHLC4 (C), cash at its level. On a Monday where a review executes and the target changes, the book is rebalanced to target at those fill prices and pays cost on the value traded. Every holding is then carried from the fill to today's close. On other days fill-then-close is just close-to-close.", False),
        ("   'NAV (harness)' is the engine's unit-based NAV with stock-level holdings. 'check − harness' shows the gap, broken down on Summary section C. The only remaining difference is that the check model re-enters equity at the parent's drifted weights, while the harness buys the parent's current published weights.", False),
        ("Trades_final / Positions_final: every harness trade of the FINAL rule, and every holding's weight before and after, with fill prices.", False),
        ("Sleeve_spells: every stretch in the sleeve: entry and exit, gold signal at entry, flips inside the spell, gold, cash and parent returns, and the sleeve return under 80/20, 20/80, 50/50 and the final rule.", False),
        ("", False),
        ("SOURCES", True),
        ("Index signals: AA/Historical Data/frozen_2026-09-25/Master/Master_{Nifty100,MC100,SC100}.xlsx (SIGN column).", False),
        ("Gold signal: AA/Historical Data/FRA_MAUc1/RSI/Final/Analysis/Master_MAUc1.xlsx (SIGN column): the desk's production ST.py (weekly candles, multiplier 2, 5-bar linearly weighted ATR) run unmodified on MAUc1, the same way the Friday job runs it for the indices (mauc1_st_production.py). Read on each review as the latest week label on or before the review.", False),
        ("Gold price data: the user's Eikon export of MAUc1 (MCX gold futures, continuous), C:/Users/manur/Downloads/MAUc1_daily1.csv, cleaned by mauc1_signal.py.", False),
        ("Sleeve prices: GOLDBEES close and the LBES total-return cash level, as used by the harness.", False),
        ("Parent baskets: Rebalance_history_by_scid_SCMO_{0003,0007,0010,0029}.csv, priced from ohlcv_eikon by quote_id.", False),
        ("Code: AA/analysis/final_strategy.py (harness runs, CSVs) and final_strategy_excel.py (this workbook). CSVs of every table are in AA/analysis/evidence/final_strategy/.", False),
    ]
    ws.column_dimensions["A"].width = 160
    for i, (txt, b) in enumerate(lines, 1):
        c = ws.cell(row=i, column=1, value=txt)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if b:
            c.font = Font(bold=True, size=12 if i == 1 else 11)
    wb.calculation.fullCalcOnLoad = True
    try:
        wb.save(XL)
        print("wrote", XL)
    except PermissionError:
        alt = XL.with_name("final_strategy_workbook_mauc1.xlsx")
        wb.save(alt)
        print("workbook is open in Excel; wrote", alt)


if __name__ == "__main__":
    main()
