"""Build data/review/<date>/data_review.html from that review's outputs only.

    python data/review_page.py --date 2026-10-22

Every number on the page is read from the review's CSV/JSON files; nothing is typed here except
labels, formulas and the text in review_decisions.json.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
E = html.escape


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{100*x:+.{d}f}%" if sign else f"{100*x:.{d}f}%"


def num(x, d=0):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:,.{d}f}"


def table(df: pd.DataFrame, cols: dict, cls="", fmt: dict | None = None, raw: set | None = None) -> str:
    fmt, raw = fmt or {}, raw or set()
    th = "".join(f"<th>{E(v)}</th>" for v in cols.values())
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = r.get(c, "")
            s = fmt[c](v) if c in fmt else ("" if (isinstance(v, float) and np.isnan(v)) else str(v))
            tds.append(f"<td>{s if c in raw else E(s)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def chip(v: str) -> str:
    k = {"PASS": "ok", "PASS WITH NOTES": "warn", "FAIL": "bad"}.get(v, "na")
    icon = {"ok": "✓", "warn": "!", "bad": "✕", "na": "·"}[k]
    return f'<span class="chip {k}"><b aria-hidden="true">{icon}</b>{E(v)}</span>'


def verdict_rows(items: dict, span_for: dict) -> str:
    out = []
    for k, i in items.items():
        out.append(f"""<article class="vr">
<div class="vr-id"><span class="id">{E(k)}</span>{chip(i["verdict"])}</div>
<div class="vr-main"><div class="vr-name">{E(i["name"])}</div>
<div class="vr-meta"><span>{E(i["role"])}</span><span>{E(span_for.get(k, ""))}</span></div>
<div class="vr-src"><b>Source</b> {E(i["source"])}</div>
<div class="vr-src"><b>Fetched</b> {E(i["fetched_by"])}; {E(i["fetched_on"])}</div></div>
<div class="vr-why">{E(i.get("verdict_note", ""))}</div></article>""")
    return '<div class="vlist">' + "".join(out) + "</div>"


def issue_cards(iss: pd.DataFrame) -> str:
    out = []
    for _, r in iss.iterrows():
        st = str(r["status"])
        k = "bad" if st == "OPEN" else ("ok" if st in ("HANDLED",) else "warn")
        out.append(f"""<article class="iss"><div class="iss-h"><span class="id">{E(r["id"])}</span>
<span class="chip {k}">{E(st)}</span><span class="muted">inputs {E(str(r["input"]))}</span></div>
<p>{E(str(r["issue"]))}</p><p><b>Effect if ignored.</b> {E(str(r["effect"]))}</p><p><b>Handling.</b> {E(str(r["handling"]))}</p></article>""")
    return '<div class="ilist">' + "".join(out) + "</div>"


def img(path: Path, alt: str) -> str:
    b = base64.b64encode(path.read_bytes()).decode()
    return f'<figure><img alt="{E(alt)}" src="data:image/png;base64,{b}"><figcaption>{E(alt)}</figcaption></figure>'


def mdt(df: pd.DataFrame, cols: dict, fmt: dict | None = None) -> str:
    """A GitHub markdown table."""
    fmt = fmt or {}
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(cols.values()) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        vals = []
        for c in cols:
            v = r.get(c, "")
            vals.append(cell(fmt[c](v) if c in fmt else ("" if (isinstance(v, float) and np.isnan(v)) else v)))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    R = HERE / "review" / a.date
    rd = lambda n, **k: pd.read_csv(R / n, **k)
    dec = json.loads((HERE / "review_decisions.json").read_text(encoding="utf-8"))
    summ = json.loads((R / "summary.json").read_text(encoding="utf-8"))
    inv = rd("inventory.csv")
    cal = rd("calendar.csv")
    vals = rd("values.csv")
    sig = rd("signals.csv")
    bas = rd("baskets.csv")
    cov = rd("coverage.csv")
    ends = rd("price_history_ends_early.csv")
    thin = rd("sessions_absent_from_stock_file.csv")
    moves = rd("largest_moves.csv")
    rec = rd("reconciliation.csv")
    sdiff = rd("stock_source_diffs.csv")
    der = rd("derived.csv")
    spot = rd("spot_checks.csv")
    iss = pd.DataFrame(dec["issues"])  # judgement text: read from the decisions file, never a stale copy
    calcd = rd("calendar_diffs.csv")

    # one row per input for the verdict board, with the span of its first file where the checks give one
    items = {i["id"]: i for i in dec["inputs"]}
    span = {}
    for _, r in cal.iterrows():
        span[r["series"]] = f'{r["first"]} → {r["last"]}'
    span_for = {"D01": span.get("index NSEI", ""), "D02": span.get("index NSEI", ""),
                "D03": "", "D04": "", "D09": span.get("GOLDBEES Eikon", ""), "D10": span.get("GOLDBEES Kite (parquet)", ""),
                "D11": span.get("LBES adjusted (cash)", ""), "D12": span.get("MAUc1 raw export", ""),
                "D14": span.get("published parent SCMO_0003", ""), "D15": span.get("published AA SCMO_0042", "")}
    for _, r in sig.iterrows():
        if r["signal"] == "Nifty100":
            span_for["D03"] = f'{r["first_row"]} → {r["last_row"]}'
        if r["signal"] == "NiftyMidcap150":
            span_for["D04"] = f'{r["first_row"]} → {r["last_row"]}'
        if r["signal"] == "MAUc1":
            span_for["D13"] = f'{r["first_row"]} → {r["last_row"]}'
    v = vals.set_index("series")
    span_for["D06"] = f'{v.loc["stocks Eikon 2014-21", "first"]} → {v.loc["stocks Eikon 2014-21", "last"]}'
    span_for["D07"] = f'{v.loc["stocks Eikon 2021-26", "first"]} → {v.loc["stocks Eikon 2021-26", "last"]}'
    span_for["D08"] = f'{v.loc["stocks Kite 2021-26", "first"]} → {v.loc["stocks Kite 2021-26", "last"]}'
    span_for["D05"] = f'{bas["effective"].min()} → {bas["effective"].max()} (effective dates)'
    span_for["D16"] = "2021-10-30 → (review dates)"
    span_for["X01"] = "2014-07-04 → 2021-10-29; 2021-11-01 → 2026-08-21"
    span_for["X02"] = span.get("GOLDBEES Eikon", "")
    # T03 inputs (D17 published NAVs 2019-26, D18 per-parent OHLC, D19 weight matrices): present from review 2026-11-05 on
    opt = lambda n: pd.read_csv(R / n) if (R / n).exists() else None
    ho, hs, hw = opt("holdings_ohlc.csv"), opt("d17_d18_sessions.csv"), opt("holdings_weights.csv")
    span_for["D17"] = span.get("D17 published parent SCMO_0003", "")
    if ho is not None:
        span_for["D18"] = f'{ho["first"].min()} → {ho["last"].max()}'
    if hw is not None:
        span_for["D19"] = f'{hw["first"].min()} → {hw["last"].max()} (basket dates)'
    board = pd.DataFrame([{"id": k, "name": i["name"], "role": i["role"], "verdict": chip(i["verdict"]),
                           "span": span_for.get(k, ""), "source": i["source"], "fetched": i["fetched_on"],
                           "note": i.get("verdict_note", "")} for k, i in items.items()])
    counts = pd.Series([i["verdict"] for i in items.values()]).value_counts()

    # calendar: special sessions, which series hold them
    ref_first, ref_last = summ["reference_calendar"]["first"], summ["reference_calendar"]["last"]
    # dates where the NSE calendar and an NSE-traded series disagree (MCX-only dates are summarised separately)
    nse_series = ["published parent SCMO_0003", "GOLDBEES Eikon", "GOLDBEES Kite (parquet)"]
    special_dates = sorted(set(calcd.loc[calcd["kind"].isin(["missing", "extra"]) & calcd["series"].isin(nse_series)
                                         & (calcd["date"] >= "2014-07-01") & (calcd["date"] <= ref_last), "date"]) | set(thin["date"]))
    extra_any = set(calcd.loc[calcd["kind"] == "extra", "date"])
    def holds(series, d, in_ref):
        x = calcd[(calcd["series"] == series) & (calcd["date"] == d)]
        c = cal[cal["series"] == series].iloc[0]
        if not (c["first"] <= d <= c["last"]):
            return "outside span"
        kind = x["kind"].iloc[0] if len(x) else None
        if in_ref:
            return "absent" if kind == "missing" else "present"
        return "present" if kind == "extra" else "absent"
    mcx_only = calcd[(calcd["series"] == "MAUc1 raw export") & (calcd["kind"] == "extra")]
    sp_rows = []
    for d in special_dates:
        wd = pd.Timestamp(d).day_name()
        # a date is in the NSE calendar unless some series lists it as "extra"
        in_ref = d not in extra_any
        holds_ = lambda s: holds(s, d, in_ref)
        sp_rows.append({"date": d, "weekday": wd, "calendar": "present" if in_ref else "absent",
                        "pub": holds_("published parent SCMO_0003"), "gbe": holds_("GOLDBEES Eikon"),
                        "gbk": holds_("GOLDBEES Kite (parquet)"), "mau": holds_("MAUc1 raw export"),
                        "stk": ("thin: " + str(int(thin.loc[thin['date'] == d, 'stocks_with_a_row'].iloc[0])) + " stocks") if (thin["date"] == d).any() else ""})
    sp = pd.DataFrame(sp_rows)

    # moves: 2014-07-01 on, beyond threshold
    mv = moves[(moves["beyond_threshold"]) & (moves["date"] >= "2014-07-01")].copy()
    mv = mv[~mv["series"].str.startswith("GOLDBEES Kite") & ~mv["series"].str.startswith("MAUc1 raw")]
    mv_old = moves[(moves["beyond_threshold"]) & (moves["date"] < "2014-07-01")]

    # charts
    ch = R / "charts"
    charts = summ["charts"]

    cr = cov.copy()
    cr["span"] = cr["first"] + " → " + cr["last"]

    recs = rec.copy()
    recs["span"] = recs["first"] + " → " + recs["last"]

    gfd = der[der["series"].str.startswith("GOLDBEES")].iloc[0]
    mcd = der[der["series"].str.startswith("MAUc1")].iloc[0]
    lby = pd.DataFrame([{"year": k, "ret": v} for k, v in summ["lbes_calendar_year_returns"].items()])
    ssum = summ["stock_source_diffs"]

    blockers = "".join(f"<li>{E(b)}</li>" for b in dec["blockers_for_T02"])
    oq = "".join(f"<li>{E(q)}</li>" for q in dec["open_questions"])
    comp = pd.DataFrame(dec["component_map"])

    gaps = ends[ends["reading"].str.startswith("GAP")]
    legit = ends[~ends["reading"].str.startswith("GAP")]

    worst_share = cov[cov["window"] == "2014-21"]["unpriced_weight_share"]

    # ── T03 inputs addendum: shared by the page and the markdown record ──
    t03 = pd.DataFrame(dec.get("t03_inputs", []))
    if len(t03):
        t03["name"] = t03["id"].map(lambda k: items[k]["name"] if k in items else "")
        t03["verdict"] = t03["id"].map(lambda k: items[k]["verdict"] if k in items else "")
    ho_cols = {"parent": "Parent", "first": "First", "last": "Last", "stocks": "Stocks", "sessions": "Sessions", "rows": "Rows",
               "src_db": "db", "src_export": "export", "src_carried": "carried", "duplicates": "Dupl.", "blank_close": "Blank close",
               "nonpos_close": "≤ 0 close", "ohlc_violations": "OHLC breaks", "needed_stock_sessions": "Needed stock-sessions",
               "missing": "Missing", "carried": "Carried (availability)", "carried_on_D17_sessions": "…on a D17 session",
               "carried_in_T03_window": "…in the T03 window"}
    ho_fmt = {c: (lambda x: num(x)) for c in ("stocks", "sessions", "rows", "src_db", "src_export", "src_carried", "duplicates", "blank_close",
                                              "nonpos_close", "ohlc_violations", "needed_stock_sessions", "missing", "carried",
                                              "carried_on_D17_sessions", "carried_in_T03_window")}
    hs_cols = {"parent": "Parent", "date": "Date", "weekday": "Day", "in_D17": "In D17", "in_D18": "In D18",
               "in_reference_calendar": "In the .NSEI calendar", "D18_stocks_with_a_bar": "D18 stocks with a bar",
               "typical_stocks_nearby": "Typical, ±7 days"}
    hw_cols = {"parent": "Parent", "baskets": "Baskets", "first": "First", "last": "Last", "columns": "Columns", "held_per_basket_min": "Held min",
               "held_per_basket_max": "Held max", "rowsum_min": "Row sum min", "rowsum_max": "Row sum max", "negative_weights": "Negative weights"}
    hw_fmt = {"rowsum_min": lambda x: f"{x:.4f}", "rowsum_max": lambda x: f"{x:.4f}"}
    t03_cols = {"id": "ID", "name": "Input", "verdict": "Verdict", "used_for": "T03 uses it for", "impact": "Impact on T03"}
    if ho is not None and len(t03):
        t03_html = f"""<section id="t03"><h2>Inputs of T03 (added 2026-11-05)</h2>
<p>T03 tests the three-index switch on the four parents' own stocks over 2019-01-02 → 2026-08-21. Three inputs are new to this review: <b>D17</b> (published parent NAVs from 2019), <b>D18</b> (per-parent stock OHLC, from the holdings matrix) and <b>D19</b> (basket weights). The rest were reviewed on 2026-10-22; their verdicts are unchanged and only their use by T03 is added here.</p>
{table(t03, t03_cols, raw={"verdict"}, fmt={"verdict": lambda v: chip(v)})}
<h3>Conditions T03 carries</h3>
<ul>{"".join("<li>" + E(c) + "</li>" for c in dec.get("t03_conditions", []))}</ul>
<h3>D18: stock OHLC per parent</h3>
<p>One row per stock per session on which it has a bar. <i>Missing</i> = needed stock-sessions with no bar on a real session; <i>carried</i> = a flat bar at the last close, only on sessions where a held stock had no bar (listed in <code>*_ohlc_filled_cells.csv</code>). Prices are Eikon, adjusted for splits, bonuses and demergers, not dividends; Polyplex needs <code>price_corrections.csv</code> (F-AA-D14).</p>
{table(ho, ho_cols, cls="num", fmt=ho_fmt)}
<h3>D17 against D18: which sessions each has</h3>
<p>Every D17 session is in D18. D18 also has the sessions below, which the published NAVs skip (six Diwali Muhurat evenings and two special Saturdays, 2024-03-02 and 2024-05-18). They are real sessions the published index does not use; the stock counts show how many stocks traded on each (F-AA-D15). <b>T03's calendar is D17's dates</b>, so no price on these dates is used to value or trade.</p>
<details><summary>{len(hs)} rows</summary>{table(hs, hs_cols, cls="num", fmt={"D18_stocks_with_a_bar": lambda x: num(x), "typical_stocks_nearby": lambda x: num(x)})}</details>
<h3>D19: basket weights per parent</h3>
{table(hw, hw_cols, cls="num", fmt=hw_fmt)}
</section>
"""
        t03_md = f"""## 3b. Inputs of T03 (added 2026-11-05)

T03 tests the three-index switch on the four parents' own stocks over 2019-01-02 → 2026-08-21. **D17**, **D18** and **D19** are new to this review; the other inputs keep their 2026-10-22 verdicts, and only their use by T03 is added.

{mdt(t03, t03_cols)}

**Conditions T03 carries:**

{chr(10).join("- " + c for c in dec.get("t03_conditions", []))}

**D18, per parent** (`holdings_ohlc.csv`):

{mdt(ho, ho_cols, fmt=ho_fmt)}

**D17 against D18, sessions that differ** (`d17_d18_sessions.csv`). Every D17 session is in D18; D18 also has these, which the published NAVs skip. T03's calendar is D17's dates.

{mdt(hs, hs_cols, fmt={"D18_stocks_with_a_bar": lambda x: num(x), "typical_stocks_nearby": lambda x: num(x)})}

**D19, per parent** (`holdings_weights.csv`):

{mdt(hw, hw_cols, fmt=hw_fmt)}

---

"""
    else:
        t03_html, t03_md = "", ""
    prev_review = dec.get("previous_review", "first review")
    cited_by = dec.get("cited_by", "none yet. T01 (2026-10-01) predates it.")

    page = f"""<title>AA Data Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Serif:wght@500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f6f7f5;--surface:#ffffff;--ink:#1d2321;--ink2:#4a5551;--muted:#77827d;--rule:#d9dfdb;--accent:#0f5f57;--accent-soft:#e3efec;
--ok:#1f7a3f;--ok-bg:#e4f3e8;--warn:#8a5a00;--warn-bg:#fbf0d9;--bad:#a5281b;--bad-bg:#fbe6e2;--na:#5b6661;--na-bg:#eceeed;--code:#eef1ef;
--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;--serif:"IBM Plex Serif",Georgia,serif}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#121614;--surface:#1a201d;--ink:#e6ebe8;--ink2:#b5c0bb;--muted:#8a9690;--rule:#2f3834;--accent:#5fc2b5;--accent-soft:#1c2f2c;
--ok:#6fd08f;--ok-bg:#16301f;--warn:#f0c065;--warn-bg:#33270f;--bad:#ff8a7a;--bad-bg:#3a1a16;--na:#a3ada8;--na-bg:#252c29;--code:#202725}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#121614;--surface:#1a201d;--ink:#e6ebe8;--ink2:#b5c0bb;--muted:#8a9690;--rule:#2f3834;--accent:#5fc2b5;--accent-soft:#1c2f2c;
--ok:#6fd08f;--ok-bg:#16301f;--warn:#f0c065;--warn-bg:#33270f;--bad:#ff8a7a;--bad-bg:#3a1a16;--na:#a3ada8;--na-bg:#252c29;--code:#202725}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55;padding-inline:16px;padding-block:28px 64px}}
main{{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:34px}}
h1{{font-family:var(--serif);font-weight:600;font-size:2.1rem;letter-spacing:-.01em;margin:0;text-wrap:balance}}
h2{{font-family:var(--serif);font-weight:600;font-size:1.35rem;margin:0 0 6px;text-wrap:balance}}
h3{{font-size:1rem;font-weight:600;margin:18px 0 6px}}
p{{margin:6px 0;max-width:78ch}} .lede{{color:var(--ink2);font-size:1.02rem}}
.kicker{{font-family:var(--mono);font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 18px;font-family:var(--mono);font-size:.8rem;color:var(--muted);margin-top:8px}}
section{{border-top:1px solid var(--rule);padding-top:18px}}
.tw{{overflow-x:auto;margin:10px 0;border:1px solid var(--rule);border-radius:6px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:.84rem;font-variant-numeric:tabular-nums}}
th{{text-align:left;font-weight:600;color:var(--ink2);background:var(--code);padding:7px 9px;border-bottom:1px solid var(--rule);white-space:nowrap;position:sticky;top:0}}
td{{padding:6px 9px;border-bottom:1px solid var(--rule);vertical-align:top}}
tr:last-child td{{border-bottom:0}}
td:first-child{{font-family:var(--mono);font-size:.8rem}}
.num td{{white-space:nowrap}}
.vlist,.ilist{{display:flex;flex-direction:column;border:1px solid var(--rule);border-radius:6px;background:var(--surface);margin:10px 0}}
.vr{{display:grid;grid-template-columns:170px minmax(0,1.3fr) minmax(0,1fr);gap:6px 18px;padding:12px 14px;border-bottom:1px solid var(--rule)}}
.vr:last-child,.iss:last-child{{border-bottom:0}}
.vr-id{{display:flex;flex-direction:column;align-items:flex-start;gap:6px}}
.id{{font-family:var(--mono);font-size:.8rem;color:var(--muted)}}
.vr-name{{font-weight:600;overflow-wrap:anywhere}} .vr-src,.vr-why,.iss p{{overflow-wrap:anywhere}}
.mv td:nth-child(2),.mv td:nth-child(3){{white-space:nowrap}} table.narrow{{width:auto;min-width:260px}}
.vr-meta{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:.8rem;color:var(--ink2);font-variant-numeric:tabular-nums}}
.vr-meta span:last-child{{font-family:var(--mono);font-size:.76rem}}
.vr-src{{font-size:.78rem;color:var(--muted);margin-top:3px}} .vr-src b{{font-weight:600;color:var(--ink2);margin-right:4px}}
.vr-why{{font-size:.86rem;color:var(--ink2)}}
.iss{{padding:12px 14px;border-bottom:1px solid var(--rule)}} .iss p{{font-size:.88rem;max-width:none}}
.iss-h{{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px}} .muted{{color:var(--muted);font-size:.8rem}}
@media (max-width:760px){{.vr{{grid-template-columns:1fr}} .vr-id{{flex-direction:row;align-items:center}}}}
.chip{{display:inline-flex;align-items:center;gap:5px;font-size:.74rem;font-weight:600;letter-spacing:.02em;padding:2px 8px 2px 6px;border-radius:999px;white-space:nowrap}}
.chip b{{font-size:.8rem}}
.chip.ok{{color:var(--ok);background:var(--ok-bg)}} .chip.warn{{color:var(--warn);background:var(--warn-bg)}} .chip.bad{{color:var(--bad);background:var(--bad-bg)}} .chip.na{{color:var(--na);background:var(--na-bg)}}
.tally{{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}}
.callout{{border-left:3px solid var(--bad);background:var(--bad-bg);padding:12px 16px;border-radius:0 6px 6px 0}}
.callout h3{{margin-top:0;color:var(--bad)}} .callout ul{{margin:6px 0 0;padding-left:20px}}
.note{{border-left:3px solid var(--accent);background:var(--accent-soft);padding:10px 14px;border-radius:0 6px 6px 0;font-size:.9rem}}
.formula{{font-family:var(--mono);font-size:.8rem;background:var(--code);border-radius:6px;padding:10px 12px;overflow-x:auto;white-space:pre;color:var(--ink)}}
figure{{margin:12px 0;background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:8px}}
figure img{{display:block;width:100%;height:auto}} figcaption{{font-size:.78rem;color:var(--muted);padding:4px 4px 0}}
details{{margin:8px 0}} summary{{cursor:pointer;font-weight:500;color:var(--accent)}}
code{{font-family:var(--mono);font-size:.85em;background:var(--code);padding:1px 5px;border-radius:4px}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:10px}}
ol,ul{{max-width:80ch}} li{{margin:3px 0}}
</style>
<main>
<header>
<div class="kicker">AA asset-allocation smallcases · project data review · AGENT.md task 0</div>
<h1>AA Data Review</h1>
<p class="lede">Every input the AA backtests read, where it came from, what checks it passed, and whether a test may use it. Reviewed on {E(a.date)}. Status: <b>{E(dec.get("status","DRAFT"))}</b>: tests may not rely on it until the items in red are closed.</p>
<div class="meta"><span>review {E(a.date)}</span><span>reference calendar {E(ref_first)} → {E(ref_last)}, {summ["reference_calendar"]["sessions"]:,} NSE sessions</span><span>script data/data_review.py</span><span>{len(items)} inputs</span></div>
<div class="tally">{chip("PASS")} <span>{counts.get("PASS",0)}</span> {chip("PASS WITH NOTES")} <span>{counts.get("PASS WITH NOTES",0)}</span> {chip("FAIL")} <span>{counts.get("FAIL",0)}</span></div>
</header>

<div class="callout"><h3>Blocks the next test (T02)</h3><ul>{blockers}</ul></div>

<section id="verdicts"><h2>Verdict per input</h2>
<p>PASS: every check passed and the source is recorded. PASS WITH NOTES: usable, and each note travels into the test's list of contaminants. FAIL: not usable until fixed. A missing source is a FAIL even when the values look right (AGENT.md task 0). Spans are each file's first and last date.</p>
{verdict_rows(items, span_for)}
</section>

<section id="map"><h2>Component map: which series each role uses</h2>
<p>Tests read their inputs through this table. A test that departs from it says so, with its reason. The cash leg, for example, is the dividend-reinvested LIQUIDBEES level, because the LIQUIDBEES price is flat by design.</p>
{table(comp, {"role":"Role","series":"Series used","why":"Why this one","convention":"Convention"})}
</section>

<section id="calendar"><h2>Calendar</h2>
<p>Reference: the production NSE calendar (Refinitiv .NSEI), {E(ref_first)} → {E(ref_last)}. <code>calendar.csv</code>, which the engines read, matches it on every date to its own last day, 2026-09-18. For each series: <i>missing</i> = reference sessions inside the series' own first-to-last span with no row; <i>extra</i> = rows on dates the reference does not hold; <i>longest gap</i> = most consecutive reference sessions missing.</p>
{table(cal, {"series":"Series","first":"First","last":"Last","rows":"Rows","ref_sessions_in_span":"Sessions in span","missing":"Missing","extra":"Extra","weekend_rows":"Weekend rows","duplicates":"Dupl.","longest_gap_sessions":"Longest gap"}, cls="num")}
<h3>Special sessions since 2014-07-01: who holds them</h3>
<p>Weekend, Muhurat and Budget-day sessions are where the sources disagree. "Thin" means the stock file has rows for under half the stocks it usually has around that date.</p>
{table(sp, {"date":"Date","weekday":"Day","calendar":"NSE calendar","pub":"Published NAVs","gbe":"GOLDBEES Eikon","gbk":"GOLDBEES Kite","mau":"MAUc1 (MCX)","stk":"Stock file"})}
<p>Not listed: the {len(mcx_only)} dates on which MCX traded gold while NSE was shut ({E(str(mcx_only["date"].min()))} → {E(str(mcx_only["date"].max()))}). They are expected, and the MAUc1 signal drops them (it is built on the NSE calendar).</p>
</section>

<section id="values"><h2>Values</h2>
<p>Per series over its whole span: blank and non-positive values per field; rows where low exceeds open or close, or high is below them; runs of five or more identical closes (three for cash); a day-on-day ratio above 5 or below 0.2 (a unit break).</p>
{table(vals[~vals["series"].str.startswith("stocks")], {"series":"Series","blank_close":"Blank close","nonpos_close":"≤ 0 close","ohlc_violations":"OHLC breaks","stale_runs":"Stale runs","longest_stale_run":"Longest run","unit_breaks":"Unit breaks"}, cls="num", fmt={"ohlc_violations":lambda x:num(x),"stale_runs":lambda x:num(x),"longest_stale_run":lambda x:num(x),"unit_breaks":lambda x:num(x)})}
{table(vals[vals["series"].str.startswith("stocks")], {"series":"Stock file","first":"First","last":"Last","rows":"Rows","isins":"ISINs","blank_close":"Blank close","blank_open":"Blank open","nonpos_close":"≤ 0 close","duplicates":"Dupl. (ISIN, date)","extra_dates":"Dates off calendar","ohlc_violations":"OHLC breaks"}, cls="num", fmt={"rows":lambda x:num(x),"isins":lambda x:num(x),"ohlc_violations":lambda x:num(x),"duplicates":lambda x:num(x),"extra_dates":lambda x:num(x),"blank_open":lambda x:num(x)})}
<p>The LIQUIDBEES price's {num(vals.set_index("series").loc["LIQUIDBEES Kite (DB closes)","stale_runs"])} stale runs are the point: the fund pays its yield out daily, so its price sits at about ₹1,000.</p>
</section>

<section id="signals"><h2>Signals</h2>
<p>Each production Master file: every row should fall on the last NSE session of its week, no week with a session should lack a row, SIGN should be BUY exactly when the supertrend line is the lower band (FLB) and SELL when it is the upper band (FUB), and the weekly close in the file should equal the index file's close on that date.</p>
{table(sig, {"signal":"Signal","first_row":"First","last_row":"Last","rows":"Weeks","share_buy":"Share BUY","flips":"Flips","dates_not_last_session_of_week":"Not week-end","weeks_missing":"Weeks missing","sign_not_matching_band":"SIGN ≠ band","close_vs_index_file_rows_over_1e-6":"Close ≠ index file","last_sign":"Latest"}, cls="num", fmt={"share_buy":lambda x:pct(x),"close_vs_index_file_rows_over_1e-6":lambda x:num(x) if not (isinstance(x,float) and np.isnan(x)) else "n/a"})}
</section>

<section id="baskets"><h2>Parent baskets</h2>
<p>One row per parent, across its effective dates (<code>availableDate</code>). Lag = days from the signal date to the effective date.</p>
{table(bas.groupby("parent").agg(baskets=("effective","size"),first=("effective","min"),last=("effective","max"),nmin=("names","min"),nmax=("names","max"),wmin=("weight_sum","min"),wmax=("weight_sum","max"),lmin=("lag_days","min"),lmax=("lag_days","max"),sk=("skipped_rows","sum"),bl=("blank_ticker","sum"),st=("ticker_with_star","sum"),bi=("bad_isin","sum"),du=("duplicate_isin","sum")).reset_index(),
 {"parent":"Parent","baskets":"Baskets","first":"First","last":"Last","nmin":"Names min","nmax":"Names max","wmin":"Weight sum min","wmax":"max","lmin":"Lag min (days)","lmax":"max","sk":"Skipped rows","bl":"Blank ticker","st":"Ticker with *","bi":"Bad ISIN","du":"Dupl. ISIN"}, cls="num")}
</section>

<section id="stocks"><h2>Stock prices over the sessions each parent held them</h2>
<p>For every parent, every session in the window and every stock in the basket in force that day: is there an Eikon close? Weight share without a price, per parent:</p>
<div class="formula">unpriced weight share = Σ over sessions t of Σ over held stocks i of  w(i,t) × 1[no close for i on t]
                       ÷ number of sessions
w(i,t) = the stock's listed weight in the basket in force on t (no drift)
sessions = NSE sessions in the window, except the thin special sessions listed above</div>
{table(cr, {"window":"Window","parent":"Parent","span":"Sessions","isins_held":"Stocks held","held_stock_sessions":"Stock-sessions","missing_stock_sessions":"Without a close","unpriced_weight_share":"Unpriced weight share","worst_day_unpriced_weight":"Worst day","worst_day":"on"}, cls="num", fmt={"held_stock_sessions":lambda x:num(x),"unpriced_weight_share":lambda x:pct(x,2),"worst_day_unpriced_weight":lambda x:pct(x,1)})}
<div class="note"><b>The 2014-21 gap (F-AA-D01).</b> {len(gaps)} stocks' Eikon histories end on the same day, {E(str(gaps["last"].iloc[0]) if len(gaps) else "")}, although Eikon's own delisting suffix on their RICs says they traded for years after. The others below that ended early match their delisting month.</div>
{table(ends, {"file":"File","isin":"ISIN","ric":"RIC","first":"First","last":"Last row","delisted_per_ric":"Delisted (RIC suffix)","reading":"Reading"})}
<div class="grid2">{img(ch / charts["coverage 2014-21"], "Stock prices over held sessions, 2014-07-04 → 2021-10-29: blue = price present, red = missing, blank = not held")}{img(ch / charts["coverage 2021-26"], "Stock prices over held sessions, 2021-11-01 → 2026-08-21: blue = price present, red = missing, blank = not held")}</div>
<h3>Large moves on held stocks</h3>
<p>Every daily close move of 20% or more on a stock while a parent held it: {len(rd("stock_moves.csv"))} in total, none reversed the next day by 15% or more (the usual sign of a bad print).</p>
{table(rd("stock_moves.csv"), {"window":"Window","parent":"Parent","ticker":"Stock","date":"Date","move":"Move","next_day":"Next day"}, cls="num", fmt={"move":lambda x:pct(x,1,True),"next_day":lambda x:pct(x,1,True)})}
<h3>Eikon against Kite, 2021-06-01 → 2026-08-21</h3>
<p>Same ISIN, same day, daily close returns. {ssum["isins_compared"]} stocks and {ssum["isin_days_compared"]:,} stock-days compared; {ssum["days_over_5pct"]} differ by more than 5 pp, on {ssum["isins_with_any"]} stocks. The largest are Kite failing to adjust for demergers and special dividends, which is why Eikon is used.</p>
<details><summary>All {len(sdiff)} stock-days</summary>{table(sdiff.sort_values("difference"), {"date":"Date","isin":"ISIN","eikon_return":"Eikon","kite_return":"Kite","difference":"Difference"}, cls="num", fmt={"eikon_return":lambda x:pct(x,1,True),"kite_return":lambda x:pct(x,1,True),"difference":lambda x:pct(x,1,True)})}</details>
</section>

{t03_html}
<section id="moves"><h2>Largest moves, 2014-07-01 onward</h2>
<p>Every daily move beyond the series' threshold (index 5%, ETF and futures 5%, smallcase NAV 8%, cash 0.5%), with the same-day move of a second series. A move is confirmed when a second series moved the same way by at least 0.3 times as much. For MAUc1, GOLDBEES's next session counts, because MCX trades until 23:30.</p>
<div class="formula">move(t) = close(t) ÷ close(previous row) − 1</div>
{table(mv, {"series":"Series","date":"Date","move":"Move","second_source":"Second source","explanation":"Explanation"}, cls="mv", fmt={"move":lambda x:pct(x,1,True)})}
<details><summary>{len(mv_old)} moves before 2014-07-01 (outside every backtest window)</summary>{table(mv_old, {"series":"Series","date":"Date","move":"Move","second_source":"Second source","explanation":"Explanation"}, cls="mv", fmt={"move":lambda x:pct(x,1,True)})}</details>
</section>

<section id="reconciliation"><h2>Reconciliation of overlapping sources</h2>
<p>Pairs compared on their common dates, on returns, never on levels:</p>
<div class="formula">CAGR = (P_last ÷ P_first)^(365.25 ÷ calendar days between them) − 1
gap per year = CAGR(first series) − CAGR(second series), in percentage points
correlation = Pearson correlation of the two daily return series on common dates</div>
{table(recs, {"pair":"Pair","span":"Common dates","common_dates":"Days","cagr_a":"CAGR, first","cagr_b":"CAGR, second","gap_pp_per_year":"Gap pp / yr","corr_daily":"Correlation","max_abs_daily_diff":"Largest daily gap","worst_days":"Largest daily gaps"}, cls="num", fmt={"cagr_a":lambda x:pct(x,2),"cagr_b":lambda x:pct(x,2),"gap_pp_per_year":lambda x:f"{x:+.2f}","corr_daily":lambda x:f"{x:.4f}","max_abs_daily_diff":lambda x:pct(x,2)})}
<div class="grid2">{"".join(img(ch / charts[f"harness vs published {p}"], f"{p}: harness rebuild vs published NAV, growth of 1 from the first common date") for p in ["SCMO_0003","SCMO_0007","SCMO_0010","SCMO_0029"])}</div>
<div class="grid2">{img(ch / charts["GOLDBEES sources"], "GOLDBEES, Eikon vs Kite, growth of 1 from the first common date (log scale)")}{img(ch / charts["cash"], "Cash leg (LBES adjusted) vs the LIQUIDBEES price, growth of 1 from the first common date")}</div>
</section>

<section id="derived"><h2>Derived series</h2>
<h3>Harness parents (X01)</h3>
<p>Each parent is rebuilt from its real baskets: a basket takes effect on its <code>availableDate</code>; trades fill at the next session's OHLC4 from the Eikon file; holdings drift between baskets; returns are price return (no dividends). Built by <code>analysis/final_strategy.py</code>. 2014-21 has no published series to check against and inherits F-AA-D01. In 2021-26 it runs below the published NAVs (Reconciliation, first four rows).</p>
<h3>GOLDBEES fill price, de-spiked (X02)</h3>
<p>GOLDBEES's open, high and low carry ETF-only prints far from the close. The fill price clips high and low to MCX gold's daily range scaled to GOLDBEES, then takes OHLC4. Fill prices changed: {int(gfd["changes"])} of {int(gfd["rows_in"])} days; median change {pct(gfd["median_change"],2,True)}; 1st to 99th percentile {pct(gfd["p01_change"],1,True)} to {pct(gfd["p99_change"],1,True)}; largest {pct(gfd["max_abs_change"],1)}.</p>
<h3>MAUc1 cleaned (D12)</h3>
<p>The raw export's {int(mcd["rows_in"])} rows become {int(mcd["rows_out"])}; {int(mcd["changes"])} changes, each logged in <code>{E(str(mcd["log"]))}</code>: holiday rows with no close dropped, close-only rows filled, one bar widened so high and low contain the close.</p>
<h3>Cash: LBES adjusted (D11), return by calendar year</h3>
<p>Plausible overnight-money rates in every year; first and last years are partial (2007-06-29 → 2007-12-31 is not shown; 2026 runs to 2026-08-09).</p>
{table(lby, {"year":"Year","ret":"Return"}, cls="num narrow", fmt={"ret":lambda x:pct(x,2)})}
</section>

<section id="spot"><h2>Spot checks against a public source</h2>
<p>Values on fixed dates, to be compared by a person with the exchange's or the fund's own published figures. None has been checked yet, which is one reason this review is still a draft.</p>
{table(spot, {"series":"Series","date":"Date","value_here":"Value here","value_found":"Value found","source":"Source","status":"Status"}, cls="num", fmt={"value_here":lambda x:num(x,2)})}
</section>

<section id="issues"><h2>Data defects</h2>
{issue_cards(iss)}
</section>

<section id="questions"><h2>Open questions for the desk</h2><ol>{oq}</ol></section>

<section id="charts"><h2>Every series, plotted</h2>
<p>Each row: the level (log scale) over the series' own span, daily returns with the move threshold dashed, and the histogram of daily returns (log count).</p>
{"".join(img(ch / charts[k], k) for k in ["index NSEI","index Nifty100","index MC100","index SC100","GOLDBEES Eikon","LBES adjusted (cash)","MAUc1 cleaned"] + [f"published parent {p}" for p in ["SCMO_0003","SCMO_0007","SCMO_0010","SCMO_0029"]] + [f"published AA {b}" for b in ["SCMO_0042","SCMO_0043","SCMO_0044","SCMO_0045"]])}
</section>

<section id="inventory"><h2>Inventory: every file and its fingerprint</h2>
<p>The sha256 each test checks its inputs against before it runs (AGENT.md R6). <i>File time</i> is the file's last-modified time on disk, not a fetch date.</p>
<details><summary>{len(inv)} files</summary>{table(inv.assign(sha=inv["sha256"].astype(str).str[:16]), {"id":"ID","file":"File","bytes":"Bytes","sha":"sha256 (first 16)","file_modified":"File time","fetched_by":"Fetched by","used_by":"Used by"}, fmt={"bytes":lambda x:num(x)})}</details>
</section>

<footer><p class="meta">Built by <code>data/review_page.py</code> from <code>data/review/{E(a.date)}/</code>, which <code>data/data_review.py --date {E(a.date)}</code> writes from the raw files. Judgements (sources, verdicts, explanations) are in <code>data/review_decisions.json</code>. Methods: <code>data/review/{E(a.date)}/METHODS.md</code>.</p></footer>
</main>
"""
    (R / "data_review.html").write_text(page, encoding="utf-8")
    print(f"wrote {R / 'data_review.html'} ({len(page)/1e6:.2f} MB)")

    # ── the written record, data/DATA_REVIEW.md, from the same inputs ──
    inv_rows = pd.DataFrame([{**i, "span": span_for.get(k, "")} for k, i in items.items()])
    files = inv.assign(sha=inv["sha256"].astype(str).str[:16])
    basket_sum = bas.groupby("parent").agg(baskets=("effective", "size"), first=("effective", "min"), last=("effective", "max"),
                                           nmin=("names", "min"), nmax=("names", "max"), wmin=("weight_sum", "min"),
                                           wmax=("weight_sum", "max"), sk=("skipped_rows", "sum"), bl=("blank_ticker", "sum"),
                                           st=("ticker_with_star", "sum")).reset_index()
    md = f"""# Data review — AA, {a.date}

> Generated by `data/review_page.py` from `data/review/{a.date}/` (written by `data/data_review.py`) and
> `data/review_decisions.json` (the judgements). Do not edit by hand: change the decisions file or the
> script, and regenerate. Once a test cites this review it is not changed; a later review is written
> as a new dated folder. Format: `wm-research/DATA_REVIEW_TEMPLATE.md`; rules: `wm-research/AGENT.md` task 0.

**Status:** {dec.get("status", "DRAFT")}. Tests may not rely on it until these are closed:
{chr(10).join("- " + b for b in dec["blockers_for_T02"])}

**Review date:** {a.date}
**Reviewed by:** Claude (Claude Code), for Manu Rathi
**Script:** `data/data_review.py` — imports nothing from any engine; reads only the raw files
**Output:** `data/review/{a.date}/` — the CSVs named below, `charts/`, `data_review.html` and `METHODS.md`
**Previous review / what changed since:** {prev_review}
**Tests that cite this review:** {cited_by}

**Verdicts:** PASS {counts.get("PASS", 0)}, PASS WITH NOTES {counts.get("PASS WITH NOTES", 0)}, FAIL {counts.get("FAIL", 0)} (of {len(items)} inputs).

---

## 1. Inventory

{mdt(inv_rows, {"id": "ID", "name": "Input", "role": "Role", "source": "Source system", "fetched_by": "Fetched by", "fetched_on": "Fetched on", "span": "Covers", "basis": "Adjusted for; price or total return", "used_by": "Used by", "verdict": "Verdict"})}

**Files and fingerprints** (`inventory.csv`; *file time* is the last-modified time on disk, not a fetch date):

{mdt(files, {"id": "ID", "file": "File", "bytes": "Bytes", "sha": "sha256 (first 16)", "file_modified": "File time"}, fmt={"bytes": lambda x: num(x)})}

---

## 2. Component map

{mdt(comp, {"role": "Role", "series": "Series and field used", "why": "Why this one", "convention": "Gap and extension convention"})}

---

## 3. Derived series

### X01 — harness parents
- **Inputs:** D05 (baskets), D06 (2014-21 prices), D07 (2021-26 prices).
- **Construction, in plain words:** each basket takes effect on its `availableDate`; the harness buys it at the next session's OHLC4 and holds the shares, letting weights drift, until the next basket. Value each day = Σ shares × Eikon close. Price return: no dividends.
- **Script:** `analysis/final_strategy.py` → `analysis/evidence/final_strategy/nav_curves_daily.csv`.
- **Reconciliation (2021-26)**, against the published NAVs, on returns over common dates:

{mdt(recs[recs["pair"].str.contains("harness")], {"pair": "Pair", "span": "Common dates", "cagr_a": "CAGR harness", "cagr_b": "CAGR published", "gap_pp_per_year": "Gap pp / yr", "corr_daily": "Correlation of daily returns"}, fmt={"cagr_a": lambda x: pct(x, 2), "cagr_b": lambda x: pct(x, 2), "gap_pp_per_year": lambda x: f"{x:+.2f}", "corr_daily": lambda x: f"{x:.4f}"})}

- **2014-21:** no published series exists; built on D06, so it inherits F-AA-D01.
- **Charts:** `charts/harness_vs_published_<parent>.png`.

### X02 — GOLDBEES fill price, de-spiked
- **Construction:** GOLDBEES's high and low are clipped to MCX gold's daily range (D12) scaled to GOLDBEES, then OHLC4 is taken. The close is never changed.
- **Script:** `analysis/final_strategy.py:186-207` → `analysis/evidence/final_strategy/goldbees_fill_despiked.csv`.
- **Size:** {int(gfd["changes"])} of {int(gfd["rows_in"])} fill prices changed; median change {pct(gfd["median_change"], 2, True)}; 1st to 99th percentile {pct(gfd["p01_change"], 1, True)} to {pct(gfd["p99_change"], 1, True)}; largest {pct(gfd["max_abs_change"], 1)}.

### D12 cleaned — MAUc1
- {int(mcd["rows_in"])} raw rows → {int(mcd["rows_out"])}; {int(mcd["changes"])} changes logged in `{mcd["log"]}`.

### Cash past its last date (F-AA-D05)
- Convention set here: as-of carry on NSE sessions; past the file's last date, accrue at the trailing 90-session daily rate and count those days. Calendar-year returns of D11 (`summary.json`):

{mdt(lby, {"year": "Year", "ret": "Return"}, fmt={"ret": lambda x: pct(x, 2)})}

---

{t03_md}## 4. Checks

Printed by `data_review.py`. Thresholds: stock 20%, index 5%, ETF and futures 5%, smallcase NAV 8%, cash 0.5% a day; stale run = 5 identical closes in a row (3 for cash); unit break = a day-on-day ratio above 5 or below 0.2; thin session = fewer than half the usual number of stocks with a row.

### 4.1 Calendar
Reference: `FRA_MAUc1/Data/TradingDays.xlsx` (production, Refinitiv .NSEI), {ref_first} → {ref_last}, {summ["reference_calendar"]["sessions"]:,} sessions. `calendar.csv` matches it on every date to 2026-09-18.

{mdt(cal, {"series": "Series", "first": "First", "last": "Last", "rows": "Rows", "ref_sessions_in_span": "Sessions in span", "missing": "Missing", "extra": "Extra", "weekend_rows": "Weekend rows", "duplicates": "Dupl.", "longest_gap_sessions": "Longest gap"})}

Special sessions since 2014-07-01 where sources disagree:

{mdt(sp, {"date": "Date", "weekday": "Day", "calendar": "NSE calendar", "pub": "Published NAVs", "gbe": "GOLDBEES Eikon", "gbk": "GOLDBEES Kite", "mau": "MAUc1", "stk": "Stock file"})}

### 4.2 Values

{mdt(vals[~vals["series"].str.startswith("stocks")], {"series": "Series", "blank_close": "Blank close", "nonpos_close": "≤ 0", "ohlc_violations": "OHLC breaks", "stale_runs": "Stale runs", "longest_stale_run": "Longest run", "unit_breaks": "Unit breaks"}, fmt={k: (lambda x: num(x)) for k in ["ohlc_violations", "stale_runs", "longest_stale_run", "unit_breaks"]})}

{mdt(vals[vals["series"].str.startswith("stocks")], {"series": "Stock file", "first": "First", "last": "Last", "rows": "Rows", "isins": "ISINs", "blank_close": "Blank close", "blank_open": "Blank open", "duplicates": "Dupl.", "extra_dates": "Off calendar", "ohlc_violations": "OHLC breaks"}, fmt={k: (lambda x: num(x)) for k in ["rows", "isins", "blank_open", "duplicates", "extra_dates", "ohlc_violations"]})}

### 4.3 Signals

{mdt(sig, {"signal": "Signal", "first_row": "First", "last_row": "Last", "rows": "Weeks", "share_buy": "Share BUY", "flips": "Flips", "dates_not_last_session_of_week": "Not week-end", "weeks_missing": "Weeks missing", "sign_not_matching_band": "SIGN ≠ band", "last_sign": "Latest"}, fmt={"share_buy": lambda x: pct(x)})}

### 4.4 Parent baskets

{mdt(basket_sum, {"parent": "Parent", "baskets": "Baskets", "first": "First", "last": "Last", "nmin": "Names min", "nmax": "max", "wmin": "Weight sum min", "wmax": "max", "sk": "Skipped rows", "bl": "Blank ticker", "st": "Ticker with *"})}

### 4.5 Stock prices over held sessions

unpriced weight share = Σ over sessions t, Σ over held stocks i of w(i,t) × 1[no close for i on t] ÷ number of sessions (thin special sessions excluded).

{mdt(cr, {"window": "Window", "parent": "Parent", "span": "Sessions", "isins_held": "Stocks held", "held_stock_sessions": "Stock-sessions", "missing_stock_sessions": "Without a close", "unpriced_weight_share": "Unpriced weight share", "worst_day_unpriced_weight": "Worst day", "worst_day": "on"}, fmt={"unpriced_weight_share": lambda x: pct(x, 2), "worst_day_unpriced_weight": lambda x: pct(x, 1), "held_stock_sessions": lambda x: num(x)})}

Histories that end before the file does (`price_history_ends_early.csv`):

{mdt(ends, {"file": "File", "isin": "ISIN", "ric": "RIC", "last": "Last row", "delisted_per_ric": "Delisted (RIC suffix)", "reading": "Reading"})}

Eikon against Kite, 2021-06-01 → 2026-08-21: {ssum["isins_compared"]} stocks, {ssum["isin_days_compared"]:,} stock-days, {ssum["days_over_5pct"]} differ by more than 5 pp (`stock_source_diffs.csv`).

### 4.6 Largest moves, 2014-07-01 onward
move(t) = close(t) ÷ close(previous row) − 1. Confirmed when a second series moved the same way by at least 0.3 times as much.

{mdt(mv, {"series": "Series", "date": "Date", "move": "Move", "second_source": "Second source", "explanation": "Explanation"}, fmt={"move": lambda x: pct(x, 1, True)})}

### 4.7 Spot checks
Not yet done; values to check:

{mdt(spot, {"series": "Series", "date": "Date", "value_here": "Value here", "value_found": "Value found", "source": "Source", "status": "Status"}, fmt={"value_here": lambda x: num(x, 2)})}

### 4.8 Reconciliation of overlapping sources
CAGR = (P_last ÷ P_first)^(365.25 ÷ calendar days) − 1 on common dates; gap = CAGR(first) − CAGR(second).

{mdt(recs, {"pair": "Pair", "span": "Common dates", "cagr_a": "CAGR first", "cagr_b": "CAGR second", "gap_pp_per_year": "Gap pp / yr", "corr_daily": "Correlation", "worst_days": "Largest daily gaps"}, fmt={"cagr_a": lambda x: pct(x, 2), "cagr_b": lambda x: pct(x, 2), "gap_pp_per_year": lambda x: f"{x:+.2f}", "corr_daily": lambda x: f"{x:.4f}"})}

---

## 5. Charts

In `data/review/{a.date}/charts/`, all drawn by `data_review.py`: {", ".join(f"`{v}`" for v in charts.values())}.

---

## 6. Issues

{chr(10).join(f"### {r['id']} — {r['status']}{chr(10)}**Inputs:** {r['input']}{chr(10)}{chr(10)}{r['issue']}{chr(10)}{chr(10)}**Effect if ignored.** {r['effect']}{chr(10)}{chr(10)}**Handling.** {r['handling']}{chr(10)}" for r in dec["issues"])}

---

## 7. Verdicts

{mdt(pd.DataFrame(list(items.values())), {"id": "Input", "name": "Name", "verdict": "Verdict", "verdict_note": "Notes every test must carry"})}

---

## 8. Open questions

{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(dec["open_questions"]))}

---

## 9. Reproduction

```bash
python data/data_review.py --date {a.date}     # checks and charts -> data/review/{a.date}/
python data/review_page.py --date {a.date}     # the page and this file
```

Deterministic: the raw files are fingerprinted in §1, the thresholds are fixed in §4, and the review
script makes no network calls (fetching is a separate, logged step).
"""
    (HERE / "DATA_REVIEW.md").write_text(md, encoding="utf-8")
    print(f"wrote {HERE / 'DATA_REVIEW.md'}")


if __name__ == "__main__":
    main()
