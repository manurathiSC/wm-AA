# -*- coding: utf-8 -*-
"""Excel workbook that rebuilds T11's NAV series with live formulas, 2014-09-01 -> 2019-01-02, four parents:
  * hold the parent (the rebuilt parent index),
  * Part A: the three-index switch with a fixed 50/50 GOLDBEES / cash sleeve (engine run `strategy_fixed50`),
  * Part B: the same switch with the MAUc1-timed sleeve, 80/20 when BUY and 20/80 when SELL (engine run `strategy`).

Inputs (blue): weekly index and MAUc1 SIGNs, stock closes and fills, raw basket weights, GOLDBEES raw bars and the MCX gold range, the LBES level,
session numbers, and the engine's NAV / stats for comparison. Everything else is a formula: state (all three BUY), gold weight, the GOLDBEES
de-spike, whether a trade happens on each candidate session and of what kind, V -> traded -> cost -> k -> units, daily NAV, statistics.
Inputs!C4 (round-trip cost in bps) drives every run: 0 / 20.8 / 50 switch on the comparison with the engine.

    python tests/T11/backcalc_workbook.py        (from AA/)  -> tests/T11/evidence/backcalc/T11_backcalc.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as CL

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import approved_data as AD  # noqa: E402

PK = AA / "tests" / "T11" / "evidence" / "backcalc"
HD = AA / "Historical Data"
MASTERS = [("Nifty100", "Nifty 100", HD / "extended_2026-10-30" / "Master" / "Master_Nifty100.xlsx"),          # D03 (as t11_engine.MASTER_DIR)
           ("MC100", "Midcap 100", HD / "extended_2026-10-30" / "Master" / "Master_MC100.xlsx"),
           ("SC100", "Smallcap 100", HD / "extended_2026-10-30" / "Master" / "Master_SC100.xlsx"),
           ("MAUc1", "MAUc1 (gold)", HD / "extended_2026-11-12" / "MAUc1_from_2003" / "Master_MAUc1.xlsx")]  # D24b (as t11_engine.D24B_DIR)
MS_FIRST, MS_LAST = pd.Timestamp("2014-01-01"), pd.Timestamp("2019-01-04")
MS_COLS = ["Date", "Index", "ST", "FUB", "FLB", "SIGN"]
MS_W = len(MS_COLS) + 2          # block width: 6 Master columns, "SIGN changed", spacer
MS0 = 5                          # IndexSignals first data row
IS = "IndexSignals"
HEAD = AA / "tests" / "T11" / "evidence" / "headline"
HM = AA / "data" / "holdings_matrix"
OUTF = PK / "T11_backcalc.xlsx"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
RUNS = [("hold_parent", "Hold the parent (rebuilt index)"), ("strategy_fixed50", "Part A: rule, 50/50 sleeve"), ("strategy", "Part B: rule, MAUc1-timed sleeve")]
T = 1070
NJ = 228                       # weekly decisions j = 0..227
SIG0, SIG1 = 5, 5 + NJ - 1     # Signals rows
D0, D1 = 5, 5 + T - 1          # Daily / GoldCash rows (row = idx + 5)

F = "Arial"
BLUE = Font(name=F, size=10, color="0000FF")
BLACK = Font(name=F, size=10, color="000000")
GREEN = Font(name=F, size=10, color="008000")
BOLD = Font(name=F, size=10, bold=True)
TITLE = Font(name=F, size=13, bold=True)
NOTE = Font(name=F, size=9, italic=True, color="595959")
HDR_FILL = PatternFill("solid", fgColor="D9E1F2")
A_FILL = PatternFill("solid", fgColor="E2EFDA")
B_FILL = PatternFill("solid", fgColor="FCE4D6")
YELLOW = PatternFill("solid", fgColor="FFFF00")
DATE, NAV, PX, UNITS, PCT, WT, SCI = "yyyy-mm-dd", "0.000000", "#,##0.0000", "0.000000000", "0.00%", "0.000000", "0.0E+00"


def c(ws, v, font=BLACK, fmt=None, fill=None, comment=None, align=None):
    x = WriteOnlyCell(ws, value=v)
    x.font = font
    if fmt:
        x.number_format = fmt
    if fill:
        x.fill = fill
    if comment:
        x.comment = Comment(comment, "T11 backcalc")
    if align:
        x.alignment = align
    return x


def hdr(ws, labels, fill=HDR_FILL):
    return [None if h is None else c(ws, h, BOLD, fill=fill, align=Alignment(wrap_text=True, vertical="center")) for h in labels]


def q(sheet: str) -> str:
    return f"'{sheet}'"


def widths(ws, ws_list):
    for k, wd in enumerate(ws_list, start=1):
        ws.column_dimensions[CL(k)].width = wd


GC = "GoldCash"
SG = "Signals"
# GoldCash columns
GC_CLOSE, GC_FILL, GC_LBES = "U", "V", "W"
GCR = lambda col: f"{GC}!${col}${D0}:${col}${D1}"  # noqa: E731
SGR = lambda col: f"{SG}!${col}${SIG0}:${col}${SIG1}"  # noqa: E731


def readme(wb):
    rd = wb.create_sheet("README")
    rd.column_dimensions["A"].width = 3
    rd.column_dimensions["B"].width = 160
    lines = [
        ("T11 back-calculation: the rebuilt parent index and the three-index rule (Part A and Part B), live formulas", TITLE),
        ("Window 2014-09-01 -> 2019-01-02, 1,070 NSE sessions (idx 0..1069); base NAV = 1.000 at 2014-09-01's close; parents SCMO_0003, 0007, 0010, 0029.", BLACK),
        ("Rebuilt from the parents' baskets and Eikon prices; no published NAV exists before 2019-01-02 to validate it. Price return: dividends are not added.", NOTE),
        ("", BLACK),
        ("HOW TO USE", BOLD),
        ("Inputs!C4 (yellow) is the round-trip cost in bps and drives every run. At 0, 20.8 or 50 the engine's own NAVs and stats appear beside the formulas, with the gap.", BLACK),
        ("Inputs!C7:C10 hold the rule's constants (de-spike tolerance, gold weights). Changing them changes the formulas' result but the engine comparison then no longer applies.", BLACK),
        ("The SIGN column of each block in IndexSignals (the raw weekly Master rows) is an input too: change one and the decisions, the state, the trades and every NAV after it follow (only sessions in each RuleA/RuleB list can trade; that list covers every possible trade session).", BLACK),
        ("TO CHECK EVERY MOVE IN OR OUT OF EQUITY AGAINST THE THREE INDEX SIGNALS", BOLD),
        ("Signals: filter 'Equity move' (column R) to the non-blank rows: each switch, its decision date, trade date, the three SIGNs that week, which of them changed since the week before (S) and which are on SELL (T).", BLACK),
        ("RuleA / RuleB: columns U-AC sit beside every candidate trade session: the decision behind it, the three SIGNs, 'Signals say' (IN iff all three BUY), 'Equity held' after the row, MAUc1, the gold weight held, and Disagree.", BLACK),
        ("InOut: every session, the SIGNs in force against the equity held by Part A and Part B of all four parents (and Part B's gold weight). Summary rows 19-23 count every disagreement (all should be 0).", BLACK),
        ("Summary: end NAV, CAGR, max drawdown, volatility, number of trades and cost paid for the 3 runs x 4 parents, beside the engine, and the largest daily NAV gap.", BLACK),
        ("", BLACK),
        ("THE RULE (T11.md section 3; = T06 / T08 on this window)", BOLD),
        ("1. Every week (decision j: 2014-09-01, then the last NSE session of each ISO week) read the latest Master row on or before that date for Nifty 100, Midcap 100 and Smallcap 100 (D03) and for MAUc1 (D24b).", BLACK),
        ("2. State = IN (1) iff all three index SIGNs are BUY, else OUT (0). Gold weight of the sleeve: Part A 0.5 always; Part B 0.8 if MAUc1 SIGN is BUY, 0.2 if SELL.", BLACK),
        ("3. Trade on the NEXT session after decision j (j >= 1) iff the state changed, or the state is OUT and the gold weight changed (Part B only). A gold flip while IN is no trade. The last decision (2019-01-02) is not traded.", BLACK),
        ("4. Basket change: on the first session on or after a basket's availableDate, only while IN; while OUT nothing trades and the next switch-in buys the basket then in force. If it falls on a switch session it is that one trade.", BLACK),
        ("5. Trade at session t with target stock share e (1 or 0), gold weight gw, basket weights w: V = SUM u_i x fill_i + u_gold x gold fill + u_cash x LBES;", BLACK),
        ("   targets: stock i e x V x w_i, GOLDBEES (1-e) x gw x V, cash (1-e) x (1-gw) x V;  traded = SUM |target - current value at fill| (every line);  cost = traded x bps/2/10,000;  k = (V-cost)/V;  units = k x target / fill.", BLACK),
        ("6. Initial position at 2014-09-01's close (state IN), no cost: u_i = (w_i/fill_i)/S with S = SUM (w_j/fill_j) x close_j, so NAV = 1.000.  Daily NAV = SUM u_i x close_i + u_gold x GOLDBEES close + u_cash x LBES level.", BLACK),
        ("7. CAGR = NAV_end^(252/(sessions-1)) - 1;  max drawdown = MIN(NAV/running peak - 1);  volatility = STDEV(daily returns) x SQRT(252).", BLACK),
        ("", BLACK),
        ("SHEETS", BOLD),
        ("Inputs, Summary.  Signals: the 228 weekly decisions (shared by the four parents), read from IndexSignals by formula, with what changed each week and the engine's decisions beside them.", BLACK),
        ("InOut: daily equity in/out against the signals for all parents.  IndexSignals: the weekly Master rows (Date, Index close, ST, FUB, FLB, SIGN) of Nifty 100, Midcap 100, Smallcap 100 and MAUc1, 2014-01-03 -> 2019-01-04.", BLACK),
        ("GoldCash: GOLDBEES raw bar, MCX range, de-spike step by step, close and fill used, LBES level (shared).", BLACK),
        ("Per parent (prefix = last 4 digits of the scid): _Weights (raw and renormalised basket weights), _Units (hold the parent: units per basket), _RuleA and _RuleB (the rule: one row per candidate trade session),", BLACK),
        ("_Daily (NAV, return, peak, drawdown for the three runs, the engine's NAVs and the gaps), _Close (close used for valuation), _Fill (trade price, OHLC4).", BLACK),
        ("RuleA / RuleB columns: Session idx (input: every session that follows a decision, plus every basket session); j row (the latest decision before it); Decision session? (1 if a decision was taken on the previous", BLACK),
        ("session); e target and gw target (that decision's state and gold weight); Decision trade? (state changed, or OUT and gw changed); Basket in force; Basket session?; Trade? (decision trade, or basket session while IN);", BLACK),
        ("Kind; e held; V at fill; Value traded; Cost; k; GOLDBEES units; LBES units; NAV at close; then the units of every stock. A row with Trade? = 0 carries the previous units forward.", BLACK),
        ("", BLACK),
        ("COLOUR CODE", BOLD),
        ("Blue = hard-coded input. Black = formula. Green = a plain link to another sheet. Yellow fill = the cell to edit. Green / orange headers = Part A / Part B.", BLACK),
        ("", BLACK),
        ("SOURCES (all APPROVED rows of data/APPROVED_DATA.md; sha256 in tests/T11/evidence/headline/inputs.csv)", BOLD),
        ("IndexSignals: D03 Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx and D24b Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx (rows without a SIGN dropped, as the engine).", BLACK),
        ("Signals' engine columns: tests/T11/evidence/backcalc/decisions.csv (the engine's state, SIGNs and the Master row dates it read).", BLACK),
        ("GoldCash: GOLDBEES D09 analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet; MCX gold daily range D24b mauc1_daily_clean_extended.csv; LBES D11 LBES_Adjusted_Price_data_extended_2026-11-05.csv as of each session.", BLACK),
        ("Close and fill: tests/T11/evidence/backcalc/close_used_<p>.csv and fill_used_<p>.csv (D18 data/holdings_matrix/<p>_ohlc.csv with price_corrections.csv; raw OHLC in stock_prices_long.csv).", BLACK),
        ("Raw weights: D19 data/holdings_matrix/<p>_holding_weight_matrix.csv (row = availableDate). Basket sessions: tests/T11/evidence/backcalc/baskets.csv.", BLACK),
        ("Engine: tests/T11/evidence/headline/daily_nav.csv and stats.csv (window full, cash lbes). Method: tests/T11/T11.md sections 1-3 and tests/T11/evidence/backcalc/README.md. Built by tests/T11/backcalc_workbook.py.", BLACK),
        ("", BLACK),
        ("CAVEATS", BOLD),
        ("Nine manual Eikon exports for delisted stocks (provenance unrecorded) are held: 574 / 123 / 556 / 122 stock-sessions in 0003 / 0007 / 0010 / 0029. SCMO_0010 has 3 carried PRAKASH bars (2017-08-08/09/10).", BLACK),
        ("The 2019 seam of the rebuilt parent against the published NAV is -0.22, +0.39, +0.45, +0.19 pp; nothing checks the rebuild before 2019. 2016-10-30 has no GOLDBEES bar (previous close used); 2017-10-19 has no stock bars (previous closes used).", BLACK),
    ]
    rd.append([])
    for text, font in lines:
        rd.append([None, c(rd, text, font, align=Alignment(wrap_text=True, vertical="top"))])


def inputs(wb):
    ws = wb.create_sheet("Inputs")
    widths(ws, [3, 42, 14, 100])
    ws.append([None, c(ws, "Inputs", TITLE)])
    ws.append([])
    ws.append([None] + hdr(ws, ["Input", "Value", "Note"]))
    rows = [("Round-trip cost (bps)", 0, "0.0", YELLOW, "Edit this. 0, 20.8 (T11 headline) and 50 (robustness) can be compared with the engine. Half is paid on each side: 20.8 bps = 10.4 bps per rupee bought or sold."),
            ("Cost per side (fraction)", "=C4/2/10000", "0.000000", None, "Formula."),
            ("Sessions per year", 252, "0", None, "T11 convention (T11.md section 3, statistics)."),
            ("GOLDBEES de-spike tolerance", 0.005, "0.000", None, "Open/high/low are clipped to the close +- (MCX gold's (high-low)/close that day + this). T03's rule, T11 step 8."),
            ("Part B gold weight when MAUc1 is BUY", 0.8, "0.00", None, "Share of the sleeve in GOLDBEES (rest in LBES cash). T08's rule."),
            ("Part B gold weight when MAUc1 is SELL", 0.2, "0.00", None, "T08's rule."),
            ("Part A gold weight (fixed)", 0.5, "0.00", None, "T06's rule.")]
    for lab, v, fmt, fill, note in rows:
        ws.append([None, c(ws, lab), c(ws, v, BLACK if isinstance(v, str) else BLUE, fmt, fill), c(ws, note, NOTE)])
    ws.freeze_panes = "A4"


def summary(wb, st):
    sm = wb.create_sheet("Summary")
    widths(sm, [3, 11, 17, 30, 11, 11, 9, 11, 9, 11, 9, 8, 10, 3, 12, 10, 11, 9, 9, 13])
    sm.append([None, c(sm, "Summary: formulas vs the T11 engine, at the cost in Inputs!C4", TITLE)])
    sm.append([None, c(sm, "Left = this workbook's formulas. Right = the engine's numbers (tests/T11/evidence/headline/stats.csv) at the same cost; 'n/a' unless the cost is 0, 20.8 or 50. Pass mark for the gap: < 1e-12.", NOTE)])
    sm.append([])
    sm.append([None] + hdr(sm, ["Parent", "Run (engine kind)", "Description", "Start", "End", "Sessions", "End NAV", "CAGR", "Max drawdown", "Volatility", "Trades", "Cost paid", None,
                               "Engine end NAV", "Engine CAGR", "Engine max DD", "Engine vol", "Engine trades", "Max |daily NAV gap|"]))
    n_eng = len(st)
    NCHK = 5
    e0 = 5 + 12 + 2 + NCHK + 1  # 12 run rows, blank, "Input checks", the checks, header -> engine rows start here
    ER = lambda col: f"${col}${e0}:${col}${e0 + n_eng - 1}"  # noqa: E731
    r = 5
    for p in PARENTS:
        tag = p[-4:]
        D, U, RA, RB = (q(f"{tag}_{x}") for x in ("Daily", "Units", "RuleA", "RuleB"))
        for kind, desc in RUNS:
            navc, retc, ddc, gapc = {"hold_parent": ("E", "F", "H", "M"), "strategy_fixed50": ("P", "Q", "S", "X"), "strategy": ("AA", "AB", "AD", "AI")}[kind]
            if kind == "hold_parent":
                ntr, cst = f"=COUNT({U}!E6:E23)", f"=SUM({U}!G6:G23)"
            else:
                R = RA if kind == "strategy_fixed50" else RB
                ntr, cst = f"=SUM({R}!K6:K400)", f"=SUM({R}!P6:P400)"
            cond = f'COUNTIFS({ER("B")},$B{r},{ER("C")},$C{r},{ER("D")},Inputs!$C$4)=1'
            look = lambda col: f'=IF({cond},SUMIFS({ER(col)},{ER("B")},$B{r},{ER("C")},$C{r},{ER("D")},Inputs!$C$4),"n/a")'  # noqa: E731
            fill = A_FILL if kind == "strategy_fixed50" else B_FILL if kind == "strategy" else None
            sm.append([None, c(sm, p, BOLD), c(sm, kind, BOLD, fill=fill), c(sm, desc), c(sm, f"={D}!B{D0}", GREEN, DATE), c(sm, f"={D}!B{D1}", GREEN, DATE),
                       c(sm, f"=COUNT({D}!A{D0}:A{D1})", BLACK, "#,##0"), c(sm, f"={D}!{navc}{D1}", GREEN, NAV), c(sm, f"=H{r}^(Inputs!$C$6/(G{r}-1))-1", BLACK, PCT),
                       c(sm, f"=MIN({D}!{ddc}{D0}:{ddc}{D1})", BLACK, PCT), c(sm, f"=STDEV({D}!{retc}{D0 + 1}:{retc}{D1})*SQRT(Inputs!$C$6)", BLACK, PCT),
                       c(sm, ntr, BLACK, "0"), c(sm, cst, BLACK, NAV), None,
                       c(sm, look("E"), BLACK, NAV), c(sm, look("F"), BLACK, PCT), c(sm, look("G"), BLACK, PCT), c(sm, look("H"), BLACK, PCT), c(sm, look("I"), BLACK, "0"),
                       c(sm, f'=IF({cond},SUMPRODUCT(MAX(ABS({D}!{gapc}{D0}:{gapc}{D1}))),"n/a")', BLACK, SCI)])
            r += 1
    sm.append([])
    sm.append([None, c(sm, "Input checks", BOLD)])
    rule_dis = "+".join(f"SUM({q(f'{p[-4:]}_Rule{x}')}!AC5:AC400)" for p in PARENTS for x in "AB")
    checks = [("Signals: weeks where the state from the SIGNs differs from the engine's state", f"=SUMPRODUCT(ABS({SGR('K')}-{SGR('X')}))", "0"),
              ("Signals: SIGNs / Master row dates read from IndexSignals that differ from the engine's decisions.csv (4 SIGNs + 4 dates x 228 weeks)", f"=SUM({SGR('AH')})", "0"),
              ("GoldCash: largest |GOLDBEES fill from the formulas - the engine's fill|", f"=SUMPRODUCT(MAX(ABS({GCR('Y')})))", SCI),
              ("RuleA / RuleB (8 sheets): candidate sessions where the equity held, or Part B's gold weight while OUT, differs from what the three SIGNs say", f"={rule_dis}", "0"),
              ("InOut: sessions x parts where the equity held, or Part B's gold weight while OUT, differs from the SIGNs in force", f"=SUM({INOUT}!Y{D0}:Y{D1})", "0")]
    assert len(checks) == NCHK
    for lab, f, fmt in checks:
        sm.append([None, c(sm, lab, NOTE), None, None, None, None, None, c(sm, f, BLACK, fmt)])
    sm.append([None] + hdr(sm, ["Engine stats (input)", "Kind", "Cost (bps)", "End NAV", "CAGR", "Max DD", "Vol", "Trades"]))
    assert r + 2 + NCHK + 1 == e0, (r, e0)
    for row in st.sort_values(["book", "kind", "cost_bps"]).itertuples():
        sm.append([None, c(sm, row.book, BLUE), c(sm, row.kind, BLUE), c(sm, float(row.cost_bps), BLUE, "0.0"), c(sm, float(row.end_nav), BLUE, NAV), c(sm, float(row.cagr), BLUE, PCT),
                   c(sm, float(row.max_dd), BLUE, PCT), c(sm, float(row.vol), BLUE, PCT), c(sm, int(row.trades), BLUE, "0")])
    sm.freeze_panes = "D5"
    return e0


def load_masters(dec):
    """The weekly Master rows (Date, Index close, ST, FUB, FLB, SIGN) of the three index signals (D03) and MAUc1 (D24b), MS_FIRST -> MS_LAST, read as the engine
    reads them (rows without a SIGN dropped, duplicate dates keep the last). Checks that 'latest row on or before the decision date' gives decisions.csv."""
    out = {}
    for key, name, path in MASTERS:
        p = AD.require(path)
        AD.check_sha(p)
        if key == "SC100":
            AD.guard_window(p, MS_FIRST)                  # standing rule 7: nothing read before 2011-11-25
        d = pd.read_excel(p, parse_dates=["Date"]).dropna(subset=["SIGN"]).sort_values("Date").drop_duplicates("Date", keep="last")
        d = d[(d["Date"] >= MS_FIRST) & (d["Date"] <= MS_LAST)][MS_COLS].reset_index(drop=True)
        assert set(d["SIGN"]) <= {"BUY", "SELL"}
        for row in dec.itertuples():
            k = d["Date"].searchsorted(pd.Timestamp(row.decision_date), side="right") - 1
            assert k >= 0 and d.at[k, "SIGN"] == getattr(row, f"sign_{key}") and d.at[k, "Date"] == pd.Timestamp(getattr(row, f"label_{key}")), (key, row.decision_date)
        out[key] = d
    return out


def ms_range(k: int, what: str, ms) -> str:
    """Absolute range of column `what` ('Date' or 'SIGN') of Master block k on IndexSignals."""
    col = CL(1 + k * MS_W + MS_COLS.index(what))
    n = len(ms[MASTERS[k][0]])
    return f"{IS}!${col}${MS0}:${col}${MS0 + n - 1}"


def index_signals(wb, ms):
    s = wb.create_sheet(IS)
    s.freeze_panes = "A5"
    widths(s, ([11, 10, 10, 10, 10, 7, 13, 3]) * len(MASTERS))
    s.append([c(s, "Weekly Master rows of the four signals, 2014-01-03 -> 2019-01-04 (inputs to Signals)", TITLE)])
    s.append([c(s, "Blue = the Master files as on disk: Date (week), Index (weekly close), ST (supertrend), FUB / FLB (final upper / lower band), SIGN. D03 Master_{Nifty100,MC100,SC100}.xlsx; "
                   "D24b Master_MAUc1.xlsx. Each decision reads the latest row dated on or before its decision date. Edit a SIGN here and every state, trade and NAV after it follows.", NOTE)])
    top = []
    for k, (_, name, path) in enumerate(MASTERS):
        top += [c(s, name, BOLD), c(s, path.relative_to(AA).as_posix(), NOTE)] + [None] * (MS_W - 2)
    s.append(top)
    head = []
    for _, name, _ in MASTERS:
        head += hdr(s, [f"{name} week", "Index close", "ST", "FUB", "FLB", "SIGN", "SIGN changed"]) + [None]
    s.append(head)
    nmax = max(len(d) for d in ms.values())
    sc = MS_COLS.index("SIGN")
    for i in range(nmax):
        r = MS0 + i
        row = []
        for k, (key, _, _) in enumerate(MASTERS):
            d = ms[key]
            if i >= len(d):
                row += [None] * MS_W
                continue
            scol = CL(1 + k * MS_W + sc)
            row += [c(s, d.at[i, "Date"].to_pydatetime(), BLUE, DATE)] + [c(s, float(d.at[i, x]), BLUE, "#,##0.00") for x in ("Index", "ST", "FUB", "FLB")] + [c(s, d.at[i, "SIGN"], BLUE)]
            row += [c(s, "" if i == 0 else f'=IF({scol}{r}<>{scol}{r - 1},{scol}{r - 1}&" -> "&{scol}{r},"")', BLACK), None]
        s.append(row)


def signals(wb, dec, ms):
    s = wb.create_sheet(SG)
    s.freeze_panes = "E5"
    widths(s, [5, 11, 8, 11, 9, 11, 9, 11, 9, 11, 7, 9, 11, 5, 9, 9, 7, 11, 34, 30, 13, 22, 3, 8, 7, 9, 9, 9, 9, 11, 11, 11, 11, 9])
    s.append([c(s, "Weekly decisions (shared by the four parents)", TITLE)])
    s.append([c(s, "E-M: the SIGN of the latest IndexSignals row dated on or before the decision date, and that row's date (formulas). State = 1 iff all three index SIGNs are BUY. "
                   "Q-V: what changed since the previous week; filter 'Equity move' to see every switch. X-AH: the engine's decisions.csv (blue) and the check.", NOTE)])
    s.append([])
    s.append(hdr(s, ["j", "Decision date", "Decision idx", "Trade date", "Nifty 100 SIGN", "Nifty 100 row date", "Midcap 100 SIGN", "Midcap 100 row date", "Smallcap 100 SIGN",
                     "Smallcap 100 row date", "State (1 = IN)", "MAUc1 SIGN", "MAUc1 row date", "g", "gw Part B", "gw Part A",
                     "Previous state", "Equity move", "Index SIGNs that changed since last week", "Index SIGNs on SELL (why OUT)", "MAUc1 changed", "Part B sleeve-only trade", None,
                     "Engine state", "State check", "Engine Nifty 100", "Engine Midcap 100", "Engine Smallcap 100", "Engine MAUc1",
                     "Engine Nifty 100 row", "Engine Midcap 100 row", "Engine Smallcap 100 row", "Engine MAUc1 row", "SIGN / row mismatches"]))
    look = {k: (ms_range(k, "Date", ms), ms_range(k, "SIGN", ms)) for k in range(len(MASTERS))}
    D_ = lambda v: pd.Timestamp(v).to_pydatetime()  # noqa: E731
    for i, row in enumerate(dec.itertuples()):
        r, p = SIG0 + i, SIG0 + i - 1
        td = D_(row.trade_date) if isinstance(row.trade_date, str) else None
        sig = []
        for k in (0, 1, 2):
            dr, sr = look[k]
            sig += [c(s, f"=INDEX({sr},MATCH($B{r},{dr},1))", BLACK), c(s, f"=INDEX({dr},MATCH($B{r},{dr},1))", BLACK, DATE)]
        dr, sr = look[3]
        on_sell = f'=IF(K{r}=1,"",MID(IF(E{r}="SELL",", Nifty 100","")&IF(G{r}="SELL",", Midcap 100","")&IF(I{r}="SELL",", Smallcap 100",""),3,100))'
        if i == 0:
            moves = [c(s, "", BLACK), c(s, f'=IF(K{r}=1,"start IN","start OUT")', BLACK), c(s, "", BLACK), c(s, on_sell, BLACK), c(s, "", BLACK), c(s, "", BLACK)]
        else:
            chg = (f'MID(IF(E{r}<>E{p},"; Nifty 100 "&E{p}&" -> "&E{r},"")&IF(G{r}<>G{p},"; Midcap 100 "&G{p}&" -> "&G{r},"")'
                   f'&IF(I{r}<>I{p},"; Smallcap 100 "&I{p}&" -> "&I{r},""),3,200)')
            moves = [c(s, f"=K{p}", BLACK, "0"), c(s, f'=IF(K{r}=Q{r},"",IF(K{r}=1,"OUT -> IN","IN -> OUT"))', BLACK), c(s, f"={chg}", BLACK), c(s, on_sell, BLACK),
                     c(s, f'=IF(L{r}<>L{p},L{p}&" -> "&L{r},"")', BLACK), c(s, f'=IF(AND(K{r}=0,Q{r}=0,O{r}<>O{p}),"gold "&TEXT(O{p},"0.0")&" -> "&TEXT(O{r},"0.0"),"")', BLACK)]
        s.append([c(s, int(row.j), BLUE, "0"), c(s, D_(row.decision_date), BLUE, DATE), c(s, int(row.decision_idx), BLUE, "0"), c(s, td if td else "not traded", BLUE, DATE)]
                 + sig + [c(s, f'=IF(AND(E{r}="BUY",G{r}="BUY",I{r}="BUY"),1,0)', BLACK, "0"),
                          c(s, f"=INDEX({sr},MATCH($B{r},{dr},1))", BLACK), c(s, f"=INDEX({dr},MATCH($B{r},{dr},1))", BLACK, DATE),
                          c(s, f'=IF(L{r}="BUY",1,0)', BLACK, "0"), c(s, f"=IF(N{r}=1,Inputs!$C$8,Inputs!$C$9)", BLACK, "0.00"), c(s, "=Inputs!$C$10", GREEN, "0.00")]
                 + moves + [None, c(s, int(row.state), BLUE, "0"), c(s, f"=K{r}-X{r}", BLACK, "0"),
                            c(s, row.sign_Nifty100, BLUE), c(s, row.sign_MC100, BLUE), c(s, row.sign_SC100, BLUE), c(s, row.sign_MAUc1, BLUE),
                            c(s, D_(row.label_Nifty100), BLUE, DATE), c(s, D_(row.label_MC100), BLUE, DATE), c(s, D_(row.label_SC100), BLUE, DATE), c(s, D_(row.label_MAUc1), BLUE, DATE),
                            c(s, f"=(E{r}<>Z{r})+(G{r}<>AA{r})+(I{r}<>AB{r})+(L{r}<>AC{r})+(F{r}<>AD{r})+(H{r}<>AE{r})+(J{r}<>AF{r})+(M{r}<>AG{r})", BLACK, "0")])


INOUT = "InOut"


def inout(wb, dec):
    """Daily: the decision in force, its three index SIGNs and MAUc1, and what each parent's Part A / Part B actually holds (from the RuleA / RuleB sheets)."""
    s = wb.create_sheet(INOUT)
    s.freeze_panes = "C5"
    widths(s, [6, 11, 6, 11, 9, 9, 9, 9, 9, 8, 3] + [8, 8, 8] * len(PARENTS) + [3, 10])
    s.append([c(s, "Equity in or out, every session: the three index SIGNs in force against what the rule holds, all four parents", TITLE)])
    s.append([c(s, "The decision in force at a session's close = the latest decision taken on an earlier session (it trades on the next session). Signals state = 1 iff all three SIGNs are BUY. "
                   "Equity held and gold weight held come from each parent's RuleA / RuleB sheet. Disagreements = parts whose equity held differs from the signals, or whose Part B gold weight differs while OUT.", NOTE)])
    s.append([])
    ph = []
    for p in PARENTS:
        ph += [f"{p[-4:]} A equity held", f"{p[-4:]} B equity held", f"{p[-4:]} B gold weight held"]
    s.append(hdr(s, ["idx", "Date", "j row in force", "Decision date", "Nifty 100", "Midcap 100", "Smallcap 100", "Signals state (1 = IN)", "MAUc1", "Signals gw Part B", None]
                 + ph + [None, "Disagreements"]))
    for t in range(T):
        r = D0 + t
        row = [c(s, f"={GC}!A{r}", GREEN, "0"), c(s, f"={GC}!B{r}", GREEN, DATE), c(s, 1 if t == 0 else f"=MATCH(A{r}-1,{SGR('C')},1)", BLACK, "0"),
               c(s, f"=INDEX({SGR('B')},C{r})", BLACK, DATE)] + [c(s, f"=INDEX({SGR(x)},$C{r})", BLACK) for x in "EGI"] + [
               c(s, f"=INDEX({SGR('K')},C{r})", BLACK, "0"), c(s, f"=INDEX({SGR('L')},C{r})", BLACK), c(s, f"=INDEX({SGR('O')},C{r})", BLACK, "0.00"), None]
        dis = []
        k0 = 12
        for p in PARENTS:
            tag = p[-4:]
            RA, RB, DS = q(f"{tag}_RuleA"), q(f"{tag}_RuleB"), q(f"{tag}_Daily")
            ca, cb, cg = CL(k0), CL(k0 + 1), CL(k0 + 2)
            row += [c(s, f"=INDEX({RA}!$M$5:$M$400,{DS}!O{r})", BLACK, "0"), c(s, f"=INDEX({RB}!$M$5:$M$400,{DS}!Z{r})", BLACK, "0"),
                    c(s, f'=INDEX({RB}!$AB$5:$AB$400,{DS}!Z{r})', BLACK, "0.00")]
            dis += [f"({ca}{r}<>$H{r})", f"({cb}{r}<>$H{r})", f'AND({cb}{r}=0,{cg}{r}<>$J{r})*1']
            k0 += 3
        row += [None, c(s, "=" + "+".join(dis), BLACK, "0")]
        s.append(row)


def goldcash(wb, g):
    s = wb.create_sheet(GC)
    s.freeze_panes = "C5"
    widths(s, [6, 11] + [9] * 7 + [6, 6] + [9] * 10 + [10, 11, 9])
    s.append([c(s, "GOLDBEES and cash (shared by the four parents)", TITLE)])
    s.append([c(s, "Blue: GOLDBEES raw bar (D09; blank = no bar), MCX gold high/low/close (D24b; blank = no MCX bar), LBES level as of the session (D11). The de-spike and the close/fill used are formulas.", NOTE)])
    s.append([])
    s.append(hdr(s, ["idx", "Date", "GB open", "GB high", "GB low", "GB close", "MCX high", "MCX low", "MCX close", "GB bar?", "MCX range?", "Band", "Clip low", "Clip high",
                     "Open clipped", "High clipped", "High final", "Low clipped", "Low final", "De-spiked OHLC4", "GOLDBEES close used", "GOLDBEES fill used", "LBES level",
                     "Engine fill", "Fill gap"]))
    nz = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
    for t, row in enumerate(g.itertuples()):
        r = D0 + t
        s.append([c(s, t, BLUE, "0"), c(s, row.date.to_pydatetime(), BLUE, DATE)]
                 + [c(s, nz(v), BLUE, PX) for v in (row.gb_open, row.gb_high, row.gb_low, row.gb_close, row.mcx_high, row.mcx_low, row.mcx_close)]
                 + [c(s, f"=IF(ISNUMBER(F{r}),1,0)", BLACK, "0"), c(s, f"=IF(AND(J{r}=1,ISNUMBER(I{r})),1,0)", BLACK, "0"),
                    c(s, f'=IF(K{r}=1,(G{r}-H{r})/I{r}+Inputs!$C$7,"")', BLACK, "0.0000"), c(s, f'=IF(K{r}=1,F{r}*(1-L{r}),"")', BLACK, PX), c(s, f'=IF(K{r}=1,F{r}*(1+L{r}),"")', BLACK, PX),
                    c(s, f"=IF(K{r}=1,MIN(MAX(C{r},M{r}),N{r}),C{r})", BLACK, PX), c(s, f"=IF(K{r}=1,MIN(D{r},N{r}),D{r})", BLACK, PX), c(s, f"=MAX(P{r},O{r},F{r})", BLACK, PX),
                    c(s, f"=IF(K{r}=1,MAX(E{r},M{r}),E{r})", BLACK, PX), c(s, f"=MIN(R{r},O{r},F{r})", BLACK, PX), c(s, f"=(O{r}+Q{r}+S{r}+F{r})/4", BLACK, PX),
                    c(s, f'=IF(J{r}=1,F{r},"no bar on T0")' if t == 0 else f"=IF(J{r}=1,F{r},U{r - 1})", BLACK, PX), c(s, f"=IF(J{r}=1,T{r},U{r})", BLACK, PX),
                    c(s, float(row.lbes_level_used), BLUE, "#,##0.000000"), c(s, float(row.goldbees_fill_used), BLUE, PX), c(s, f"=V{r}-X{r}", BLACK, SCI)])


def parent(wb, p, bas, dec, nav):
    tag = p[-4:]
    cu = pd.read_csv(PK / f"close_used_{p}.csv", index_col=0)
    fu = pd.read_csv(PK / f"fill_used_{p}.csv", index_col=0)
    stocks = list(cu.columns)
    assert list(fu.columns) == stocks and len(cu) == T
    n = len(stocks)
    b = bas[bas["book"] == p].sort_values("basket_no").reset_index(drop=True)
    nb = len(b)
    assert nb == 19
    wm = pd.read_csv(HM / f"{p}_holding_weight_matrix.csv", index_col=0)
    wm.index = pd.to_datetime(wm.index)
    raw = wm.loc[b["available_date"].values, stocks]
    WS, US, DS, CS, FS = (q(f"{tag}_{x}") for x in ("Weights", "Units", "Daily", "Close", "Fill"))
    RS = 31                                                                       # Rule sheets: first stock column (AE)
    lastW, lastC, lastU, lastR = CL(5 + n), CL(1 + n), CL(10 + n), CL(RS - 1 + n)  # stocks: Weights F.., Close/Fill B.., Units K.., Rule AE..
    FILL_RNG = f"{FS}!$B$2:${lastC}${T + 1}"
    WREN = f"{WS}!$F$28:${lastW}${27 + nb}"
    UC = f"{US}!$C$5:$C${4 + nb}"
    dates = pd.to_datetime(cu.index)

    # Weights
    w = wb.create_sheet(f"{tag}_Weights")
    w.freeze_panes = "F5"
    widths(w, [9, 12, 12, 9, 11])
    w.append([c(w, f"{p}: basket weights, 2014-09-01 -> 2019-01-02", TITLE)])
    w.append([c(w, f"Rows 5-23: raw listed weights (D19 data/holdings_matrix/{p}_holding_weight_matrix.csv, row = availableDate). Rows 28-46: renormalised to 1 (traded).", NOTE)])
    w.append([])
    w.append(hdr(w, ["Basket", "availableDate", "Session date", "Session idx", "Raw sum"] + stocks))
    for i in range(nb):
        r = 5 + i
        w.append([c(w, int(b.at[i, "basket_no"]), BLUE), c(w, b.at[i, "available_date"].to_pydatetime(), BLUE, DATE), c(w, b.at[i, "session_date"].to_pydatetime(), BLUE, DATE),
                  c(w, int(b.at[i, "idx"]), BLUE, "0", comment="Index of the first NSE session on or after availableDate (0 = 2014-09-01)." if i == 0 else None),
                  c(w, f"=SUM(F{r}:{lastW}{r})", BLACK, WT)] + [c(w, float(v), BLUE, WT) for v in raw.iloc[i].values])
    w.append([])
    w.append([])
    w.append([c(w, "Renormalised weights = raw / raw sum", BOLD)])
    w.append(hdr(w, ["Basket", "availableDate", "Session date", "Session idx", "Sum"] + stocks))
    for i in range(nb):
        r, rr = 28 + i, 5 + i
        w.append([c(w, f"=A{rr}", GREEN), c(w, f"=B{rr}", GREEN, DATE), c(w, f"=C{rr}", GREEN, DATE), c(w, f"=D{rr}", GREEN, "0"), c(w, f"=SUM(F{r}:{lastW}{r})", BLACK, WT)]
                 + [c(w, f"={CL(6 + k)}{rr}/$E{rr}", BLACK, WT) for k in range(n)])

    # Units (hold the parent)
    u = wb.create_sheet(f"{tag}_Units")
    u.freeze_panes = "K5"
    widths(u, [8, 12, 9, 9, 11, 11, 11, 11, 11, 3])
    u.append([c(u, f"{p}: hold the parent, units held per basket, cost from Inputs!C4", TITLE)])
    u.append([c(u, "Row 5 = the free initial position at 2014-09-01 (also the rule's: it starts IN). Each later row = a basket change on its session at that session's fills; units held from its close.", NOTE)])
    u.append([])
    u.append(hdr(u, ["Basket", "Session date", "Session idx", "Last idx held", "V at fill", "Value traded", "Cost", "k = (V-cost)/V", "NAV at close", None] + stocks))
    for i in range(nb):
        r, wr = 5 + i, 28 + i
        row = [c(u, f"={WS}!A{wr}", GREEN), c(u, f"={WS}!C{wr}", GREEN, DATE), c(u, f"={WS}!D{wr}", GREEN, "0"), c(u, f"=C{r + 1}-1" if i < nb - 1 else f"={T - 1}", BLACK, "0")]
        if i == 0:
            row += [c(u, "initial", NOTE), c(u, "no trade", NOTE), c(u, 0, BLACK, NAV), c(u, 1, BLACK, "0.000000")]
            units = [c(u, f"={CL(11 + k)}$26/$F$26", BLACK, UNITS) for k in range(n)]
        else:
            prev, fills, wrow = f"K{r - 1}:{lastU}{r - 1}", f"INDEX({FILL_RNG},$C{r}+1,0)", f"{WS}!$F${wr}:${lastW}${wr}"
            row += [c(u, f"=SUMPRODUCT({prev},{fills})", BLACK, NAV), c(u, f"=SUMPRODUCT(ABS($E{r}*{wrow}-{prev}*{fills}))", BLACK, NAV),
                    c(u, f"=F{r}*Inputs!$C$5", BLACK, "0.00000000"), c(u, f"=(E{r}-G{r})/E{r}", BLACK, "0.00000000")]
            units = [c(u, f"=IF({WS}!{CL(6 + k)}{wr}>0,$H{r}*$E{r}*{WS}!{CL(6 + k)}{wr}/INDEX({FS}!{CL(2 + k)}$2:{CL(2 + k)}${T + 1},$C{r}+1),0)", BLACK, UNITS) for k in range(n)]
        row += [c(u, f"=INDEX({DS}!$E${D0}:$E${D1},C{r}+1)", GREEN, NAV), None] + units
        u.append(row)
    u.append([])
    u.append([])
    u.append([None] * 4 + [c(u, "S = SUM (w/fill) x close at T0", BOLD), c(u, f"=SUMPRODUCT(K26:{lastU}26,{CS}!B2:{lastC}2)", BLACK, "0.0000000000"), None, None,
                           c(u, "w / fill at T0 ->", BOLD), None]
             + [c(u, f"=IF({FS}!{CL(2 + k)}2>0,{WS}!{CL(6 + k)}28/{FS}!{CL(2 + k)}2,0)", BLACK, UNITS) for k in range(n)])

    # RuleA / RuleB: candidate trade sessions
    cand = sorted({int(i) + 1 for i in dec["decision_idx"].values[1:] if int(i) + 1 < T} | {int(i) for i in b["idx"] if int(i) > 0})
    sess = [0] + cand
    NE = len(sess)
    E0, E1 = 5, 5 + NE - 1
    rule_ranges = {}
    for part, gwcol, fill_ in (("A", "P", A_FILL), ("B", "O", B_FILL)):
        R = wb.create_sheet(f"{tag}_Rule{part}")
        R.freeze_panes = "D5"
        assert CL(RS) == "AE"
        widths(R, [6, 9, 11, 6, 9, 8, 8, 9, 8, 9, 7, 15, 7, 11, 11, 11, 11, 11, 11, 11, 11, 9, 9, 9, 8, 8, 8, 9, 8, 3])
        title = "Part A, fixed 50/50 sleeve (engine run strategy_fixed50)" if part == "A" else "Part B, MAUc1-timed sleeve 80/20 or 20/80 (engine run strategy)"
        R.append([c(R, f"{p}: the three-index rule, {title}; cost from Inputs!C4", TITLE)])
        R.append([c(R, "One row per session on which a trade can happen (the session after every decision, and every basket session). Trade? = 1: the trade is worked out on that row; 0: the units carry forward. "
                       "U-AD: the decision behind the row (taken on an earlier session), its three index SIGNs read straight from Signals, what they say, what is held after the row, and a check.", NOTE)])
        R.append([])
        R.append(hdr(R, ["Row", "Session idx", "Session date", "j row", "Decision session?", "e target", "gw target", "Decision trade?", "Basket in force", "Basket session?", "Trade?",
                         "Kind", "e held", "V at fill", "Value traded", "Cost", "k = (V-cost)/V", "GOLDBEES units", "LBES units", "NAV at close",
                         "Decision date", "Nifty 100 SIGN", "Midcap 100 SIGN", "Smallcap 100 SIGN", "Signals say", "Equity held", "MAUc1 SIGN", "Gold weight held", "Disagree (1 = yes)", None]
                    + stocks, fill_))
        SK, SGW = SGR("K"), SGR(gwcol)
        navcol = "P" if part == "A" else "AA"
        for i, s_ in enumerate(sess):
            r = E0 + i
            sigcols = [c(R, f"=INDEX({SGR('B')},$D{r})", BLACK, DATE)] + [c(R, f"=INDEX({SGR(x)},$D{r})", BLACK) for x in "EGI"] + [
                c(R, f'=IF(AND(V{r}="BUY",W{r}="BUY",X{r}="BUY"),"IN","OUT")', BLACK), c(R, f'=IF(M{r}=1,"IN","OUT")', BLACK), c(R, f"=INDEX({SGR('L')},$D{r})", BLACK),
                c(R, f'=IF(M{r}=1,"",G{r})' if i == 0 else f'=IF(M{r}=1,"",IF(K{r}=1,G{r},AB{r - 1}))', BLACK, "0.00"),
                c(R, f"=IF(Y{r}<>Z{r},1,IF(AND(M{r}=0,AB{r}<>G{r}),1,0))", BLACK, "0"), None]
            assert len(sigcols) == RS - 21
            if i == 0:
                row = [c(R, 0, BLACK, "0"), c(R, 0, BLUE, "0"), c(R, f"=INDEX({GCR('B')},B{r}+1)", GREEN, DATE), c(R, 1, BLACK, "0"), c(R, "", BLACK),
                       c(R, f"=INDEX({SK},D{r})", BLACK, "0"), c(R, f"=INDEX({SGW},D{r})", BLACK, "0.00"), c(R, 0, BLACK, "0"), c(R, 0, BLACK, "0"), c(R, 0, BLACK, "0"), c(R, 0, BLACK, "0"),
                       c(R, "initial (no cost)", NOTE), c(R, f"=F{r}", BLACK, "0"), c(R, "", BLACK), c(R, "", BLACK), c(R, "", BLACK), c(R, "", BLACK),
                       c(R, f"=(1-F{r})*G{r}/INDEX({GCR(GC_CLOSE)},1)", BLACK, UNITS), c(R, f"=(1-F{r})*(1-G{r})/INDEX({GCR(GC_LBES)},1)", BLACK, UNITS),
                       c(R, f"=INDEX({DS}!${navcol}${D0}:${navcol}${D1},B{r}+1)", GREEN, NAV)] + sigcols
                row += [c(R, f"=$F{r}*{US}!{CL(11 + k)}5", BLACK, UNITS) for k in range(n)]
            else:
                pr = r - 1
                prev = f"{CL(RS)}{pr}:{lastR}{pr}"
                fills = f"INDEX({FILL_RNG},$B{r}+1,0)"
                gf, lv = f"INDEX({GCR(GC_FILL)},$B{r}+1)", f"INDEX({GCR(GC_LBES)},$B{r}+1)"
                wrow = f"INDEX({WREN},$I{r}+1,0)"
                row = [c(R, i, BLACK, "0"), c(R, s_, BLUE, "0"), c(R, f"=INDEX({GCR('B')},B{r}+1)", GREEN, DATE),
                       c(R, f"=MATCH(B{r}-1,{SGR('C')},1)", BLACK, "0"), c(R, f"=IF(INDEX({SGR('C')},D{r})=B{r}-1,1,0)", BLACK, "0"),
                       c(R, f"=INDEX({SK},D{r})", BLACK, "0"), c(R, f"=INDEX({SGW},D{r})", BLACK, "0.00"),
                       c(R, f"=IF(AND(E{r}=1,D{r}>1),IF(OR(F{r}<>INDEX({SK},D{r}-1),AND(F{r}=0,G{r}<>INDEX({SGW},D{r}-1))),1,0),0)", BLACK, "0"),
                       c(R, f"=MATCH(B{r},{UC},1)-1", BLACK, "0"), c(R, f"=IF(INDEX({UC},I{r}+1)=B{r},1,0)", BLACK, "0"),
                       c(R, f"=IF(OR(H{r}=1,AND(J{r}=1,F{r}>0)),1,0)", BLACK, "0"),
                       c(R, f'=IF(K{r}=0,"",IF(H{r}=0,"basket_change",IF(F{r}>M{pr},"switch_in",IF(F{r}<M{pr},"switch_out","sleeve_rebalance"))))', BLACK),
                       c(R, f"=IF(K{r}=1,F{r},M{pr})", BLACK, "0"),
                       c(R, f'=IF(K{r}=1,SUMPRODUCT({prev},{fills})+R{pr}*{gf}+S{pr}*{lv},"")', BLACK, NAV),
                       c(R, f'=IF(K{r}=1,SUMPRODUCT(ABS(F{r}*N{r}*{wrow}-{prev}*{fills}))+ABS((1-F{r})*G{r}*N{r}-R{pr}*{gf})+ABS((1-F{r})*(1-G{r})*N{r}-S{pr}*{lv}),"")', BLACK, NAV),
                       c(R, f'=IF(K{r}=1,O{r}*Inputs!$C$5,"")', BLACK, "0.00000000"), c(R, f'=IF(K{r}=1,(N{r}-P{r})/N{r},"")', BLACK, "0.00000000"),
                       c(R, f"=IF(K{r}=1,Q{r}*(1-F{r})*G{r}*N{r}/{gf},R{pr})", BLACK, UNITS), c(R, f"=IF(K{r}=1,Q{r}*(1-F{r})*(1-G{r})*N{r}/{lv},S{pr})", BLACK, UNITS),
                       c(R, f"=INDEX({DS}!${navcol}${D0}:${navcol}${D1},B{r}+1)", GREEN, NAV)] + sigcols
                for k in range(n):
                    wk = f"INDEX({WS}!{CL(6 + k)}$28:{CL(6 + k)}${27 + nb},$I{r}+1)"
                    row.append(c(R, f"=IF($K{r}=1,IF($F{r}*{wk}>0,$Q{r}*$F{r}*$N{r}*{wk}/INDEX({FS}!{CL(2 + k)}$2:{CL(2 + k)}${T + 1},$B{r}+1),0),{CL(RS + k)}{pr})", BLACK, UNITS))
            R.append(row)
        rule_ranges[part] = q(f"{tag}_Rule{part}")

    # Daily
    d = wb.create_sheet(f"{tag}_Daily")
    d.freeze_panes = "C5"
    widths(d, [7, 11, 7, 3] + [10] * 9 + [3] + [7] + [10] * 9 + [3] + [7] + [10] * 9)
    d.append([c(d, f"{p}: daily NAV, base 1.000 at 2014-09-01, cost from Inputs!C4", TITLE)])
    d.append([c(d, "Hold the parent (E-M), Part A (O-X), Part B (Z-AI). NAV = SUMPRODUCT(units in force, closes) + GOLDBEES units x close + LBES units x level. Engine NAVs (blue) from tests/T11/evidence/headline/daily_nav.csv.", NOTE)])
    d.append([])
    blk = lambda nm: [f"{nm} NAV", f"{nm} return", f"{nm} peak", f"{nm} drawdown", f"Engine {nm} 0 bps", f"Engine {nm} 20.8 bps", f"Engine {nm} 50 bps", f"Engine {nm} at cost", f"{nm} gap"]  # noqa: E731
    d.append(hdr(d, ["idx", "Date", "Basket", None] + blk("Parent")) + [None] + hdr(d, ["Rule A row"] + blk("Part A"), A_FILL) + [None] + hdr(d, ["Rule B row"] + blk("Part B"), B_FILL))
    nv = {(run, cst): nav[(nav["book"] == p) & (nav["run"] == run) & (nav["cost_bps"] == cst)].sort_values("idx")["nav"].values
          for run in ("hold_parent", "strategy_fixed50", "strategy") for cst in (0.0, 20.8, 50.0)}

    def stats_block(r, t, navcol, retcol, peakcol, run, first):
        e_ = [c(d, float(nv[(run, cst)][t]), BLUE, NAV) for cst in (0.0, 20.8, 50.0)]
        cE, cA, cB = (CL(first + 4), CL(first + 5), CL(first + 6))
        return [c(d, None if t == 0 else f"={navcol}{r}/{navcol}{r - 1}-1", BLACK, PCT), c(d, f"={navcol}{r}" if t == 0 else f"=MAX({peakcol}{r - 1},{navcol}{r})", BLACK, NAV),
                c(d, f"={navcol}{r}/{peakcol}{r}-1", BLACK, PCT)] + e_ + [
                c(d, f'=IF(Inputs!$C$4=0,{cE}{r},IF(Inputs!$C$4=20.8,{cA}{r},IF(Inputs!$C$4=50,{cB}{r},"n/a")))', BLACK, NAV),
                c(d, f'=IF(ISNUMBER({CL(first + 7)}{r}),{navcol}{r}/{CL(first + 7)}{r}-1,"n/a")', BLACK, SCI)]

    RA, RB = rule_ranges["A"], rule_ranges["B"]
    for t in range(T):
        r = D0 + t
        crow = f"{CS}!B{t + 2}:{lastC}{t + 2}"
        row = [c(d, t, BLUE, "0"), c(d, dates[t].to_pydatetime(), BLUE, DATE), c(d, f"=MATCH(A{r},{UC},1)-1", BLACK, "0"), None,
               c(d, f"=SUMPRODUCT(INDEX({US}!$K$5:${lastU}${4 + nb},C{r}+1,0),{crow})", BLACK, NAV)] + stats_block(r, t, "E", "F", "G", "hold_parent", 5) + [None]
        for Rs, first, run in ((RA, 15, "strategy_fixed50"), (RB, 26, "strategy")):
            rc, navc, peakc = CL(first), CL(first + 1), CL(first + 3)
            row += [c(d, f"=MATCH(A{r},{Rs}!$B${E0}:$B${E1},1)", BLACK, "0"),
                    c(d, f"=SUMPRODUCT(INDEX({Rs}!${CL(RS)}${E0}:${lastR}${E1},{rc}{r},0),{crow})+INDEX({Rs}!$R${E0}:$R${E1},{rc}{r})*{GC}!{GC_CLOSE}{r}+INDEX({Rs}!$S${E0}:$S${E1},{rc}{r})*{GC}!{GC_LBES}{r}",
                      BLACK, NAV)] + stats_block(r, t, navc, CL(first + 2), peakc, run, first + 1)
            if first == 15:
                row.append(None)
        d.append(row)

    # Close and Fill (inputs)
    for name, df, what in (("Close", cu, "close used for valuation"), ("Fill", fu, "trade price (OHLC4)")):
        x = wb.create_sheet(f"{tag}_{name}")
        x.freeze_panes = "B2"
        x.column_dimensions["A"].width = 11
        x.append([c(x, "Date", BOLD, fill=HDR_FILL, comment=f"{p}: {what}; source tests/T11/evidence/backcalc/{name.lower()}_used_{p}.csv. Row 2 = idx 0 = 2014-09-01.")]
                 + [c(x, s, BOLD, fill=HDR_FILL) for s in stocks])
        for t in range(T):
            x.append([c(x, dates[t].to_pydatetime(), BLUE, DATE)] + [c(x, float(v), BLUE, PX) for v in df.iloc[t].values])
    print(p, "stocks", n, "candidate sessions", NE)


def main():
    nav = pd.read_csv(PK / "nav_daily.csv")
    bas = pd.read_csv(PK / "baskets.csv", parse_dates=["available_date", "session_date"])
    decs = pd.read_csv(PK / "decisions.csv")
    sg = pd.read_csv(PK / "sessions_gold_cash.csv", parse_dates=["date"])
    st = pd.read_csv(HEAD / "stats.csv")
    st = st[st["kind"].isin([k for k, _ in RUNS]) & (st["window"] == "full") & (st["cash"] == "lbes")]
    dec = decs[decs["book"] == PARENTS[0]].sort_values("j").reset_index(drop=True)
    cols = ["decision_idx", "state", "g", "sign_Nifty100", "sign_MC100", "sign_SC100", "sign_MAUc1"]
    for p in PARENTS[1:]:                                       # the four books share the decision and gold series
        assert decs[decs["book"] == p].sort_values("j")[cols].reset_index(drop=True).equals(dec[cols])
    g = sg[sg["book"] == PARENTS[0]].sort_values("idx").reset_index(drop=True)
    assert len(dec) == NJ and len(g) == T

    ms = load_masters(dec)
    wb = Workbook(write_only=True)
    readme(wb)
    inputs(wb)
    summary(wb, st)
    signals(wb, dec, ms)
    inout(wb, dec)
    index_signals(wb, ms)
    goldcash(wb, g)
    for p in PARENTS:
        parent(wb, p, bas, dec, nav)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTF      # optional output path (e.g. while the workbook is open in Excel)
    wb.save(out)
    print("written", out, f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
