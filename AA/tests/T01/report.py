"""
Build evidence/report.html for T01 from shipped evidence only, with the shared AA page CSS
(AA/analysis/why_report_template.html). Every number on the page is computed here from
evidence/headline/*.csv; the reference config's percentiles are cross-checked against the
values analyse.py printed in analysis.log, and the build refuses to write on a mismatch.

    python AA/tests/T01/report.py
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence" / "headline"
TPL = HERE.parents[1] / "analysis" / "why_report_template.html"
OUT = HERE / "evidence" / "report.html"
R, COST = "pct_w65_q25", 20.8
BOOKS = ["SCMO_0042", "SCMO_0043", "SCMO_0044", "SCMO_0045"]
PARENT = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
WIN = {"W1": "2015-07-31 → 2021-10-29 · parents rebuilt from their real baskets",
       "W2": "2021-11-01 → 2026-08-21 · published parent NAVs"}
FAMILY = [("pct_", "Position in the recent range (percentile)"), ("sma_", "Price vs its moving average"),
          ("tsmom_", "Sign of the trailing return"), ("ddhigh_", "Fall from the 52-week high"),
          ("st_weekly", "Supertrend on the smallcase's own weekly candles"), ("triple", "Market-index rule (descriptive)")]
LABEL = {
    "pct_w65_q25": "65 days, bottom 25 (your rule)", "pct_w65_hyst": "65 days, out < 25, back ≥ 50",
    "pct_w65_step": "65 days, 100 / 50 / 0 stepped", "pct_w65_q25_daily": "65 days, bottom 25, checked daily",
    "triple": "N100, MC100, SC100 all BUY", "triple_and_pct25": "Triple AND 65-day percentile ≥ 25",
    "st_weekly": "Weekly supertrend, ×2, 5-week ATR",
}


DD_CONFIGS = ["hold", "pct_w65_q25", "pct_w65_hyst", "ddhigh_250_x10", "sma_200", "st_weekly", "triple"]
DD_LABEL = {"hold": "Hold the smallcase", "pct_w65_q25": "Your rule (65 days, bottom 25)", "pct_w65_hyst": "65 days, out < 25, back ≥ 50",
            "ddhigh_250_x10": "More than 10% below the 52-week high", "sma_200": "Below its 200-day average",
            "st_weekly": "Supertrend on own weekly candles", "triple": "Market-index rule (descriptive)"}


def label(c: str) -> str:
    if c in LABEL:
        return LABEL[c]
    if m := re.fullmatch(r"pct_w(\d+)_q(\d+)", c):
        return f"{m[1]} days, bottom {m[2]}"
    if m := re.fullmatch(r"sma_(\d+)", c):
        return f"Below its {m[1]}-day average"
    if m := re.fullmatch(r"tsmom_(\d+)", c):
        return f"{m[1]}-day return below 0"
    if m := re.fullmatch(r"ddhigh_250_x(.+)", c):
        return f"More than {m[1].replace('p', '.')}% below the 52-week high"
    return c


def family(c: str) -> str:
    return next(f for p, f in FAMILY if c.startswith(p))


def pct(obs: float, draws: np.ndarray, higher_better: bool = True) -> float:
    tol = 1e-12 * max(1.0, abs(obs))
    worse = (draws < obs - tol) if higher_better else (draws > obs + tol)
    eq = np.abs(draws - obs) <= tol
    return float((worse.sum() + 0.5 * eq.sum()) / len(draws) * 100)


def r(x, d=4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), d)


def main():
    real = pd.read_csv(EV / "realisations.csv", keep_default_na=False, na_values=[""])
    real = real[real.cost_bps == COST].copy()
    bh = pd.read_csv(EV / "realisations.csv", keep_default_na=False, na_values=[""]).query("kind == 'bh'").set_index(["book", "window"])
    strat = real[real.kind == "strategy"].set_index(["config", "book", "window"])
    null = real[real.kind == "null"]
    g = {k: v.cagr.to_numpy() for k, v in null.groupby(["config", "book", "window"])}

    # every config x book x window: percentile, edge
    rows = []
    for (c, b, w), s in strat.iterrows():
        d = g[(c, b, w)]
        rep = s.n_switches >= 4 and 0.05 <= s.share_sleeve_weeks <= 0.95
        rows.append({"config": c, "book": b, "window": w, "cagr": s.cagr, "max_dd": s.max_dd, "pct": pct(s.cagr, d),
                     "edge": s.cagr - np.median(d), "null_sd": np.std(d, ddof=1), "reportable": rep,
                     "share": s.share_sleeve_weeks, "switches": int(s.n_switches),
                     "bh_cagr": bh.loc[(b, w), "cagr"], "bh_dd": bh.loc[(b, w), "max_dd"],
                     "calmar": s.calmar, "bh_calmar": bh.loc[(b, w), "calmar"]})
    T = pd.DataFrame(rows)

    # cross-check R against analysis.log (analyse.py's own numbers)
    log = (HERE / "analysis.log").read_text(encoding="utf-8")
    sec = log[log.index("--- headline: return against the null"):log.index("--- headline: risk")]
    for b in BOOKS:
        for w in ("W1", "W2"):
            m = re.search(rf"\| {w} \| {b} \({PARENT[b]}\) \| 20\.8 \| ([-\d.]+)% \|.*?\| ([-\d.]+) \| [-\d.]+ \| [-\d.]+ \| [-\d.]+ \| [-\d.]+ \| \d+ \|", sec)
            assert m, (b, w)
            x = T[(T.config == R) & (T.book == b) & (T.window == w)].iloc[0]
            assert abs(x.cagr * 100 - float(m[1])) < 0.006, (b, w, x.cagr, m[1])
            assert abs(x.pct - float(m[2])) < 0.051, (b, w, x.pct, m[2])

    # sweep summary per config x window
    sweep = []
    for c, gc in T.groupby("config", sort=False):
        row = {"config": c, "label": label(c), "family": family(c), "ref": c == R, "desc": c.startswith("triple")}
        for w in ("W1", "W2"):
            x = gc[gc.window == w]
            row[w] = {"n90": int(((x.pct >= 90) & x.reportable).sum()), "med_pct": r(x.pct.median(), 1),
                      "med_edge": r(x.edge.median()), "avg_cagr": r(x.cagr.mean()), "avg_bh": r(x.bh_cagr.mean()),
                      "avg_dd": r(x.max_dd.mean()), "avg_bh_dd": r(x.bh_dd.mean()), "share": r(x.share.mean(), 3),
                      "nrep": int(x.reportable.sum())}
        sweep.append(row)
    order = [p for p, _ in FAMILY]
    sweep.sort(key=lambda z: (next(i for i, p in enumerate(order) if z["config"].startswith(p)), z["config"] != R))

    # drawdown measures for every sweep row (drawdown_profile.py; every path reproduces the engine)
    DPall = pd.read_csv(HERE / "evidence" / "diagnostics" / "drawdown_profile.csv")
    for row in sweep:
        for w in ("W1", "W2"):
            x = DPall[(DPall.window == w) & (DPall.config == row["config"])]
            assert len(x) == 4, (row["config"], w)
            row[w].update({"below10": r(x.below10_share.mean(), 3), "longest": int(round(x.longest_dd_days.mean())),
                           "ulcer": r(x.ulcer.mean(), 2), "pct_ulcer": r(x.pct_ulcer.median(), 1)})
    hold_dd = {}
    for w in ("W1", "W2"):
        x = DPall[(DPall.window == w) & (DPall.config == "hold")]
        hold_dd[w] = {"cagr": r(x.cagr.mean()), "max_dd": r(x.max_dd.mean()), "below10": r(x.below10_share.mean(), 3),
                      "longest": int(round(x.longest_dd_days.mean())), "ulcer": r(x.ulcer.mean(), 2)}

    # reference config: per book, the null draws, and the daily path
    ref = []
    for w in ("W1", "W2"):
        for b in BOOKS:
            x = T[(T.config == R) & (T.book == b) & (T.window == w)].iloc[0]
            ref.append({"window": w, "book": b, "parent": PARENT[b], "cagr": r(x.cagr), "bh": r(x.bh_cagr), "pct": r(x.pct, 1),
                        "edge": r(x.edge), "mde": r(2.8 * x.null_sd), "null_med": r(float(np.median(g[(R, b, w)]))),
                        "dd": r(x.max_dd), "bh_dd": r(x.bh_dd), "calmar": r(x.calmar, 3), "bh_calmar": r(x.bh_calmar, 3),
                        "share": r(x.share, 3), "switches": int(x.switches),
                        "draws": [r(v) for v in np.sort(g[(R, b, w)])]})
    dr = pd.read_csv(EV / "daily_reference.csv", parse_dates=["date"])
    dr = dr[dr.cost_bps == COST]
    paths = {}
    for (b, w), x in dr.groupby(["book", "window"]):
        x = x.sort_values("date")
        paths[f"{w}|{b}"] = {"d": x.date.dt.strftime("%Y-%m-%d").tolist(), "nav": [r(v, 5) for v in x.nav],
                             "bh": [r(v, 5) for v in x.nav_bh], "eq": [r(v, 3) for v in x.w_equity]}

    # verdict counts, recomputed here (the same rules as analyse.py)
    def count(w, f):
        x = T[(T.config == R) & (T.window == w)]
        return int(f(x).sum())
    verdict = {
        "C1": {w: count(w, lambda x: (x.pct >= 90) & x.reportable) for w in ("W1", "W2")},
        "C2": {w: count(w, lambda x: (x.max_dd - x.bh_dd) * 100 >= 5.0) for w in ("W1", "W2")},
        "C3": {w: count(w, lambda x: x.calmar > x.bh_calmar) for w in ("W1", "W2")},
    }
    assert verdict["C1"] == {"W1": 2, "W2": 0} and verdict["C2"] == {"W1": 3, "W2": 0} and verdict["C3"] == {"W1": 3, "W2": 0}, verdict

    # drawdown profile (drawdown_profile.py, added after the run; its paths reproduce the engine exactly)
    DP = pd.read_csv(HERE / "evidence" / "diagnostics" / "drawdown_profile.csv")
    dd_rows = []
    for w in ("W1", "W2"):
        for c in DD_CONFIGS:
            x = DP[(DP.window == w) & (DP.config == c)]
            assert len(x) == 4, (w, c)
            dd_rows.append({"window": w, "config": c, "label": DD_LABEL[c], "cagr": r(x.cagr.mean()), "max_dd": r(x.max_dd.mean()),
                            "below10": r(x.below10_share.mean(), 3), "longest": int(round(x.longest_dd_days.mean())),
                            "ulcer": r(x.ulcer.mean(), 2),
                            "pct_ulcer": None if c == "hold" else r(x.pct_ulcer.median(), 1),
                            "pct_longest": None if c == "hold" else r(x.pct_longest_dd_days.median(), 1)})
    dd_ref = []
    for w in ("W1", "W2"):
        for b in BOOKS:
            h = DP[(DP.window == w) & (DP.config == "hold") & (DP.book == b)].iloc[0]
            x = DP[(DP.window == w) & (DP.config == R) & (DP.book == b)].iloc[0]
            dd_ref.append({"window": w, "book": b, "below10": r(x.below10_share, 3), "h_below10": r(h.below10_share, 3),
                           "longest": int(x.longest_dd_days), "h_longest": int(h.longest_dd_days),
                           "ulcer": r(x.ulcer, 2), "h_ulcer": r(h.ulcer, 2), "pct_ulcer": r(x.pct_ulcer, 1),
                           "pct_below_any": r(x.underwater_share, 3), "h_below_any": r(h.underwater_share, 3)})

    payload = {"ref": ref, "paths": paths, "sweep": sweep, "verdict": verdict, "win": WIN, "books": BOOKS, "parent": PARENT,
               "dd": dd_rows, "dd_ref": dd_ref, "hold_dd": hold_dd,
               "uw_range": [r(DP.underwater_share.min(), 3), r(DP.underwater_share.max(), 3)]}
    css = TPL.read_text(encoding="utf-8").split("<style>")[1].split("</style>")[0]
    html = PAGE.replace("/*__CSS__*/", css).replace("__DATA__", json.dumps(payload, separators=(",", ":"), allow_nan=False))
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT, round(len(html) / 1024), "KB")


PAGE = r"""<title>Own-Momentum Test</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap">
<style>
/*__CSS__*/
.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:22px 0 8px}
.kpi{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.kpi .v{font-family:var(--serif);font-size:22px;line-height:1.2;margin-top:6px}
.kpi .s{font-size:12.5px;color:var(--text-secondary);margin-top:4px}
.chip{display:inline-block;font:600 11px var(--mono);letter-spacing:.05em;padding:2px 7px;border-radius:4px;border:1px solid currentColor;vertical-align:2px}
.chip.fail{color:var(--neg)} .chip.part{color:var(--s4)} .chip.pass{color:var(--pos)}
@media (max-width:760px){.kpis{grid-template-columns:1fr}}
td.h{background:color-mix(in srgb,var(--pos) calc(var(--a)*1%),transparent)} td.c{background:color-mix(in srgb,var(--neg) calc(var(--a)*1%),transparent)}
tr.ref td{background:var(--band)} tr.desc td{color:var(--text-secondary)} tr.fam td{font:600 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding-top:16px;border-bottom:1px solid var(--baseline)}
.ideas td{white-space:normal;vertical-align:top;font-family:var(--sans);font-size:13px;text-align:left} .ideas td:first-child{font-weight:600;min-width:150px}
.ideas{min-width:760px}
#sweepT th,#sweepT td{padding:7px 7px} #sweepT td{font-size:12px} #sweepT td.l{font-size:12.5px;white-space:normal;min-width:190px}
</style>

<div class="wrap">
  <p class="eyebrow">AA · test T01 · pre-registered · the four parent smallcases · after 20.8 bps round-trip cost</p>
  <h1>A 65-day percentile on the smallcase's own index does not tell you when to leave it</h1>
  <p class="sub">Your rule (move to 50/50 gold and cash when today's close is in the bottom 25% of the last 65) helped in the 2018–20 small-cap crashes, then lost to simply holding the smallcase in 2021–26. Its exits beat the same exits at random weeks in only 2 of 4 books in 2015–21 and 0 of 4 in 2021–26; 3 of 4 in each were needed.</p>
  <p class="meta">Signal at the week's last close, trade next session at its close · sleeve 50% GOLDBEES / 50% LBES · null: the rule's own weekly target series rotated (237–312 draws per book) · design fixed before any run: <code>AA/tests/T01/T01.md</code> · methods: <code>AA/tests/T01/evidence/METHODS.md</code></p>

  <div class="kpis" id="kpis"></div>

  <h2 id="ideas">Ways to judge a smallcase's momentum from its index</h2>
  <p>Seven families of signal, and what this test found for the ones it ran. "Tested" rows are scored in the sweep below; the others need data beyond the index series or a different switch target.</p>
  <div class="tw"><table class="ideas"><thead><tr><th>Family</th><th>What it asks</th><th>Strength</th><th>Weakness</th><th>Here</th></tr></thead><tbody id="ideaT"></tbody></table></div>
  <p class="cap">Ways to move the weight, all compatible with any family: all-or-nothing; stepped (100% / 50% / 0% by band, tested as "65 days, 100 / 50 / 0 stepped"); hysteresis (leave below 25, return only above 50, tested); weekly checks at Friday's close with Monday trades (the reference) or daily checks (tested).</p>

  <h2 id="null">Your rule against the same exits at random weeks</h2>
  <p>Each grey dot is one rotation of the rule's own weekly in/out series: the same share of weeks in gold and cash, the same number of switches, placed at different weeks. If the rule read the smallcase's weakness, its result (the large mark) would sit at the right of its cloud. The tick is simply holding the smallcase.</p>
  <div class="card"><div class="legend"><span class="key"><i class="sw" style="background:var(--muted);border-radius:50%"></i>random timing, same exposure</span><span class="key"><i class="sw" style="background:var(--s2)"></i>your rule</span><span class="key"><i class="sw" style="background:var(--text-primary);width:2px"></i>hold the smallcase</span></div><div id="strip"></div></div>
  <p class="cap" id="stripCap"></p>
  <div class="tw"><table id="refT"></table></div>

  <h2 id="curve">The rule's path against holding</h2>
  <div class="controls"><span class="panel-title">Book</span><div class="seg" id="bk"></div><span class="panel-title">Period</span><div class="seg" id="pr"></div></div>
  <div class="card"><div class="legend"><span class="key"><i class="sw" style="background:var(--s2)"></i>your rule, after cost</span><span class="key"><i class="sw" style="background:var(--s1)"></i>hold the smallcase</span><span class="key"><i class="sw" style="background:var(--band);box-shadow:inset 0 0 0 1px var(--baseline)"></i>weeks in gold and cash</span></div><div id="chart"></div></div>
  <p class="cap">Growth of 1 on a log scale, daily closes. Shaded where the rule held less than half its weight in the smallcase.</p>

  <h2 id="drawdown">Drawdowns and time under water</h2>
  <p>Return is half the story; how deep and how long a book stays below its last high is the other half. On daily NAV after cost: the worst fall; the share of days spent 10% or more below the previous high; the longest stretch from a high back to a new high, in calendar days; and the Ulcer index, the root-mean-square depth below the last high, which weights deep and long falls together. These measures were added after the test ran, at your request, so they are descriptive: no pass/fail was set for them in advance.</p>
  <div class="tw"><table id="ddT"></table></div>
  <p class="cap" id="ddCap"></p>
  <div class="tw"><table id="ddRefT"></table></div>

  <h2 id="sweep">Every rule tried: return and drawdown, against holding and against random timing</h2>
  <p>One row per rule, for the period chosen. <b>Timing vs random</b>: median across the four books of the rule's percentile in its own random-timing cloud; "Edge" is its CAGR minus the cloud's median; "≥ 90th" counts books where it beat at least 90% of its draws. <b>Return and drawdown</b>: 4-book averages after cost, coloured green where better than holding the smallcase (the first row) and red where worse. <b>Ulcer vs random</b>: median across books of the share of random-timing draws with a deeper, longer drawdown profile. Slower rules lose less in 2021–26, but none clears the timing bar in more than one book, and with 28 rules tried the best in each book is no better than the best of random draws (35th–83rd percentile).</p>
  <div class="controls"><span class="panel-title">Period</span><div class="seg" id="swp"></div></div>
  <div class="tw"><table id="sweepT"></table></div>
  <p class="cap"><b>Pct</b>: median percentile of the rule's CAGR in its random-timing cloud. <b>≥10% down</b>: share of days at least 10% below the previous high. <b>Longest DD</b>: the longest stretch from a high to the next new high, in calendar days. <b>Ulcer</b>: root-mean-square depth below the last high. <b>Ulcer pct</b>: median share of random-timing draws with a higher Ulcer. Return columns are the pre-registered sweep (descriptive); the drawdown columns were added after the run, so they are descriptive too and set no pass/fail. Percentile cells are tinted: green above 50 (better than random timing), red below. The two market-index rows are context, not part of the 28.</p>

  <h2 id="next">What would move this forward</h2>
  <ul>
    <li><b>More books, not more settings.</b> Per book, this design can only detect a timing edge of 12–18 pp a year (2.8 × the spread of the random-timing draws). Running the slower rules on many more smallcases' published series is the only way to see a 5 pp edge.</li>
    <li><b>Ask the relative question.</b> "Is the smallcase doing well" is mostly about its selection versus its benchmark. A rule on smallcase ÷ Nifty 50 would say whether to switch to the index, not to gold — untested here.</li>
    <li><b>The market-index rule is still the stronger lead,</b> though regime-bound: on these same mechanics it beat random timing in 4 of 4 books in 2021–26 and 0 of 4 in 2015–21, and adding your percentile gate on top did not improve it.</li>
  </ul>

  <div class="foot"><p><b>Caveats.</b> Before 2021-11 the parents are the backtest harness's rebuild from their real baskets (price return, about 0.5–3.3 pp a year below the published series where both exist), and every series here had been looked at before this test, so no period is unseen. The index has closes only, so trades are at the next session's close, not its OHLC4. Gold's 2024–26 rally flatters any rule that sits in the sleeve then; a cash-only sleeve fails the same tests. CAGR here counts 252 sessions a year (the repo's backtest convention); NSE has about 247, so these levels run 0.2–0.5 pp above a calendar-year CAGR (holding 0042 in 2021–26: 15.30% here, 14.96% on calendar years). The final-strategy page uses calendar years, so compare levels across the two pages with that in mind; comparisons within this page are unaffected.</p>
  <p><b>Checks.</b> An independent checker re-derived every signal, decision and trade and the end value of every rule from the raw files (459,722 comparisons, 0 failures) and caught a deliberately corrupted copy; 192,584 point-in-time checks over 78,088 decisions found 0 violations; a second, separate re-run from the raw files (<code>check_page.py</code>) reproduces every number on this page (400 checks, 0 failures); an adversarial review recomputed every verdict. Findings F-AA-S01–S03, F-AA-M01 are in <code>T01.md</code> §5.</p></div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById("data").textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pc = (x, d=1) => x == null ? "–" : (x*100).toFixed(d).replace("-", "−") + "%";
const pp = (x, d=1) => x == null ? "–" : (x >= 0 ? "+" : "−") + Math.abs(x*100).toFixed(d);
const NS = "http://www.w3.org/2000/svg";
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
const avg = a => a.reduce((s, v) => s + v, 0) / a.length;

// KPIs
const V = D.verdict, ref = D.ref;
const chip = (c, w1, w2) => (w1 >= 3 && w2 >= 3) ? '<span class="chip pass">PASS</span>' : (w1 >= 3 || w2 >= 3) ? `<span class="chip part">FAIL — ${w1 >= 3 ? "2015–21" : "2021–26"} only</span>` : '<span class="chip fail">FAIL</span>';
const a = w => [avg(ref.filter(r => r.window === w).map(r => r.cagr)), avg(ref.filter(r => r.window === w).map(r => r.bh))];
const [a1, b1] = a("W1"), [a2, b2] = a("W2");
$("#kpis").innerHTML = [
  ["Times the weakness?", chip("C1", V.C1.W1, V.C1.W2), `Beat ≥ 90% of random timings in ${V.C1.W1} of 4 books (2015–21) and ${V.C1.W2} of 4 (2021–26); 3 needed in each.`],
  ["Cuts the worst fall?", chip("C2", V.C2.W1, V.C2.W2), `At least 5 pp shallower than holding in ${V.C2.W1} of 4 books (2015–21), ${V.C2.W2} of 4 (2021–26).`],
  ["Average return, 4 books", `${pc(a2)} <span style="font-size:15px;color:var(--muted)">vs ${pc(b2)} holding</span>`, `2021–26. In 2015–21: ${pc(a1)} vs ${pc(b1)}.`],
].map(([k, v, s]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");

// ideas table
const sw = Object.fromEntries(D.sweep.map(s => [s.config, s]));
const famMed = (pre) => { const xs = D.sweep.filter(s => s.config.startsWith(pre) && !s.desc); const m = w => xs.map(s => s[w].med_pct).sort((x, y) => x - y); const lo = w => m(w)[0], hi = w => m(w)[m(w).length-1]; return `tested (${xs.length}): median percentile ${lo("W1")}–${hi("W1")} in 2015–21, ${lo("W2")}–${hi("W2")} in 2021–26`; };
const IDEAS = [
  ["Position in the recent range", "Is today's close near the bottom of the last N closes? (your rule)", "Simple, scale-free, fast", "Ignores the size of moves: in a tight flat range a 1% dip reads as 'bottom 25%', so it whipsaws", famMed("pct_")],
  ["Direction of the trend", "Is the N-day return negative, or price below its 50/100/200-day average?", "Well studied; slow versions trade rarely", "Late at turns", famMed("sma_") + "; trailing return " + famMed("tsmom_").replace("tested ", "")],
  ["Damage from the peak", "Is the index more than X% below its 52-week high?", "Ignores flat markets; acts only on real falls", "Exits after part of the fall", famMed("ddhigh_")],
  ["Move scaled by volatility", "Is the move bigger than normal noise? (supertrend on the smallcase's own weekly candles)", "Same tool as the index signals", "Needs a window to settle", `tested (1): percentile ${sw.st_weekly.W1.med_pct} in 2015–21, ${sw.st_weekly.W2.med_pct} in 2021–26`],
  ["Trend quality or flatness", "Is the series trending or chopping? (efficiency ratio, R² of a trend line)", "Targets 'flat' directly", "No direction on its own; pair it with a direction rule", "only as the stepped 100 / 50 / 0 rule"],
  ["Relative strength", "Is the smallcase lagging its benchmark?", "Asks whether the selection is failing", "Its answer is a different index, not gold", "not tested"],
  ["Breadth inside the basket", "What share of holdings are above their 50-day average?", "Often turns before the index", "Needs holdings' prices, not the index", "not tested"],
];
$("#ideaT").innerHTML = IDEAS.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("");

// strip chart: null draws vs rule vs hold, per window, per book
function strip(){
  const host = $("#strip"); host.innerHTML = ""; host.classList.add("chartbox");
  const W = Math.max(320, host.clientWidth || 800), narrow = W < 560;
  const m = {l: narrow ? 52 : 120, r: narrow ? 46 : 70, t: 22, b: 30}, rowH = 34, gapW = 30;
  const rows = ref.length, H = m.t + rows * rowH + gapW + m.b;
  const all = ref.flatMap(r => r.draws.concat([r.cagr, r.bh]));
  let lo = Math.floor(Math.min(...all) * 20) / 20, hi = Math.ceil(Math.max(...all) * 20) / 20;
  const X = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
  const svg = el("svg", {class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Rule CAGR against random-timing draws, per book and period"}, host);
  for (let k = Math.round(lo * 20); k <= Math.round(hi * 20); k++){ const t = k / 20, x = X(t); el("line", {x1: x, x2: x, y1: m.t - 6, y2: H - m.b, class: k === 0 ? "base" : "grid"}, svg); if (!narrow || k % 2 === 0) el("text", {x, y: H - m.b + 16, class: "tick", "text-anchor": "middle"}, svg).textContent = (k * 5) + "%"; }
  el("text", {x: W - m.r, y: H - 4, class: "tick", "text-anchor": "end"}, svg).textContent = "CAGR after cost";
  el("text", {x: W - m.r + 8, y: m.t - 8, class: "tick"}, svg).textContent = "beats %";
  ref.forEach((r, i) => {
    const y = m.t + i * rowH + (r.window === "W2" ? gapW : 0) + rowH / 2;
    if (i === 0 || r.window !== ref[i-1].window){ el("text", {x: 0, y: y - rowH/2 - 4, class: "elabel"}, svg).textContent = r.window === "W1" ? "2015–21" : "2021–26"; }
    el("text", {x: m.l - 8, y: y + 4, class: "tick", "text-anchor": "end"}, svg).textContent = narrow ? r.book.slice(-4) : `${r.book.slice(-4)} · parent ${r.parent.slice(-4)}`;
    r.draws.forEach((v, j) => { const jy = ((j * 37) % 17) / 16 - 0.5; el("circle", {cx: X(v), cy: y + jy * (rowH - 12), r: 1.8, fill: "var(--muted)", "fill-opacity": .38}, svg); });
    const bx = X(r.bh); el("line", {x1: bx, x2: bx, y1: y - rowH/2 + 3, y2: y + rowH/2 - 3, stroke: "var(--text-primary)", "stroke-width": 2}, svg).appendChild(el("title", {})).textContent = `Hold: ${pc(r.bh)}`;
    const c = el("circle", {cx: X(r.cagr), cy: y, r: 6, fill: "var(--s2)", stroke: "var(--surface-1)", "stroke-width": 2}, svg);
    el("title", {}, c).textContent = `${r.book} ${r.window}: rule ${pc(r.cagr)}, beats ${r.pct}% of ${r.draws.length} random timings; hold ${pc(r.bh)}`;
    el("text", {x: W - m.r + 8, y: y + 4, class: "elabel"}, svg).textContent = r.pct.toFixed(1);
  });
}
$("#stripCap").textContent = "Right-hand numbers: the share of random timings the rule beat (its percentile). The test needed 90 or more in 3 of 4 books in each period.";
$("#refT").innerHTML = `<thead><tr><th>Period</th><th>Book (parent)</th><th>Rule CAGR</th><th>Hold</th><th>Random median</th><th>Edge (pp)</th><th>Percentile</th><th>Detectable edge (pp)</th><th>Worst fall</th><th>Hold's worst fall</th><th>Weeks in sleeve</th><th>Switches</th></tr></thead><tbody>` +
  ref.map(r => `<tr><td>${r.window === "W1" ? "2015–21" : "2021–26"}</td><td>${r.book.slice(-4)} (${r.parent.slice(-4)})</td><td>${pc(r.cagr)}</td><td>${pc(r.bh)}</td><td>${pc(r.null_med)}</td><td class="${r.edge >= 0 ? "pos" : "neg"}">${pp(r.edge)}</td><td>${r.pct.toFixed(1)}</td><td>${(r.mde*100).toFixed(1)}</td><td>${pc(r.dd)}</td><td>${pc(r.bh_dd)}</td><td>${pc(r.share, 0)}</td><td>${r.switches}</td></tr>`).join("") + "</tbody>";

// equity chart
let book = D.books[0], per = "W2";
function seg(host, vals, labels, get, set){ host.innerHTML = vals.map((v, i) => `<button type="button" aria-pressed="${v === get()}" data-i="${i}">${labels[i]}</button>`).join(""); host.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { set(vals[+b.dataset.i]); host.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); curve(); })); }
function curve(){
  const P = D.paths[`${per}|${book}`], host = $("#chart"); host.innerHTML = ""; host.classList.add("chartbox");
  const W = Math.max(320, host.clientWidth || 800), H = 300, m = {l: 44, r: 16, t: 10, b: 24};
  const T = P.d.map(d => Date.parse(d + "T00:00:00Z")), vals = P.nav.concat(P.bh).filter(v => v > 0);
  const lo = Math.log(Math.min(...vals)) - 0.03, hi = Math.log(Math.max(...vals)) + 0.03;
  const X = t => m.l + (t - T[0]) / (T[T.length-1] - T[0]) * (W - m.l - m.r), Y = v => m.t + (hi - Math.log(v)) / (hi - lo) * (H - m.t - m.b);
  const svg = el("svg", {class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Growth of 1, rule vs holding"}, host);
  let s = null; P.eq.forEach((e, i) => { if (e < 0.5 && s === null) s = i; if ((e >= 0.5 || i === P.eq.length - 1) && s !== null){ el("rect", {x: X(T[s]), y: m.t, width: Math.max(1, X(T[i]) - X(T[s])), height: H - m.t - m.b, fill: "var(--band)"}, svg); s = null; } });
  [0.5, 0.75, 1, 1.5, 2, 3, 4, 6].filter(v => Math.log(v) >= lo && Math.log(v) <= hi).forEach(v => { el("line", {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 1 ? "base" : "grid"}, svg); el("text", {x: m.l - 6, y: Y(v) + 4, class: "tick", "text-anchor": "end"}, svg).textContent = v; });
  const y0 = new Date(T[0]).getUTCFullYear(), y1 = new Date(T[T.length-1]).getUTCFullYear();
  for (let y = y0 + 1; y <= y1; y++){ el("text", {x: X(Date.UTC(y, 0, 1)), y: H - 6, class: "tick", "text-anchor": "middle"}, svg).textContent = y; }
  const line = (k, col, w) => el("path", {d: P[k].map((v, i) => `${i ? "L" : "M"}${X(T[i]).toFixed(1)},${Y(v).toFixed(1)}`).join(""), fill: "none", stroke: col, "stroke-width": w}, svg);
  line("bh", "var(--s1)", 1.8); line("nav", "var(--s2)", 2.4);
  const xh = el("line", {y1: m.t, y2: H - m.b, class: "xhair", visibility: "hidden"}, svg);
  const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; host.appendChild(tip);
  const ov = el("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"}, svg);
  const mv = ev => { const rc = svg.getBoundingClientRect(), px = (ev.clientX - rc.left) / rc.width * W, t = T[0] + (px - m.l) / (W - m.l - m.r) * (T[T.length-1] - T[0]);
    let a = 0, b = T.length - 1; while (a < b){ const mid = (a + b + 1) >> 1; if (T[mid] <= t) a = mid; else b = mid - 1; }
    const x = X(T[a]); xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("visibility", "visible");
    tip.innerHTML = `<div class="d">${P.d[a]}</div><div class="r"><span><i class="sw" style="background:var(--s2)"></i>Rule</span><span>${P.nav[a].toFixed(3)}</span></div><div class="r"><span><i class="sw" style="background:var(--s1)"></i>Hold</span><span>${P.bh[a].toFixed(3)}</span></div><div class="r"><span>In the smallcase</span><span>${pc(P.eq[a], 0)}</span></div>`;
    tip.hidden = false; const bw = host.clientWidth; let left = x / W * bw + 12; if (left + tip.offsetWidth > bw) left = x / W * bw - tip.offsetWidth - 12; tip.style.left = Math.max(0, left) + "px"; tip.style.top = "6px"; };
  ov.addEventListener("pointermove", mv); ov.addEventListener("pointerdown", mv); ov.addEventListener("pointerleave", () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); });
}
seg($("#bk"), D.books, D.books.map(b => `${b.slice(-4)} · ${D.parent[b].slice(-4)}`), () => book, v => book = v);
seg($("#pr"), ["W1", "W2"], ["2015–21", "2021–26"], () => per, v => per = v);

// sweep table
const tint = p => { const a = Math.min(40, Math.abs(p - 50) * 0.8); return `class="${p >= 50 ? "h" : "c"}" style="--a:${a.toFixed(0)}"`; };
let swPer = "W2";
function sweepTable(){
  const H = D.hold_dd[swPer], dn = x => x.toLocaleString("en-IN");
  const vs = (v, hv, higherBetter) => Math.abs(v - hv) < 1e-9 ? "" : ((v > hv) === higherBetter ? "pos" : "neg");
  let h = `<thead><tr><th></th><th colspan="3" style="text-align:center">Timing vs random</th><th colspan="5" style="text-align:center">Return and drawdown (4-book average)</th><th>vs random</th></tr>` +
    `<tr><th>Rule</th><th>Pct</th><th>Edge (pp)</th><th>≥ 90th</th><th>CAGR</th><th>Worst fall</th><th>≥10% down</th><th>Longest DD</th><th>Ulcer</th><th>Ulcer pct</th></tr></thead><tbody>`;
  h += `<tr class="hl"><td class="l"><b>Hold the smallcase</b></td><td>–</td><td>–</td><td>–</td><td>${pc(H.cagr)}</td><td>${pc(H.max_dd)}</td><td>${pc(H.below10, 0)}</td><td>${dn(H.longest)}</td><td>${H.ulcer.toFixed(1)}</td><td>–</td></tr>`;
  let fam = "";
  D.sweep.forEach(s => {
    if (s.family !== fam){ fam = s.family; h += `<tr class="fam"><td colspan="10">${esc(fam)}</td></tr>`; }
    const x = s[swPer];
    h += `<tr class="${s.ref ? "ref" : ""} ${s.desc ? "desc" : ""}"><td class="l">${esc(s.label)}${s.ref ? " ◂" : ""}</td>` +
      `<td ${tint(x.med_pct)}>${x.med_pct.toFixed(1)}</td><td>${pp(x.med_edge)}</td><td>${x.n90} of 4</td>` +
      `<td class="${vs(x.avg_cagr, H.cagr, true)}">${pc(x.avg_cagr)}</td><td class="${vs(x.avg_dd, H.max_dd, true)}">${pc(x.avg_dd)}</td>` +
      `<td class="${vs(x.below10, H.below10, false)}">${pc(x.below10, 0)}</td><td class="${vs(x.longest, H.longest, false)}">${dn(x.longest)}</td>` +
      `<td class="${vs(x.ulcer, H.ulcer, false)}">${x.ulcer.toFixed(1)}</td><td ${tint(x.pct_ulcer)}>${x.pct_ulcer.toFixed(0)}</td></tr>`;
  });
  $("#sweepT").innerHTML = h + "</tbody>";
}
seg($("#swp"), ["W1", "W2"], ["2015–21", "2021–26"], () => swPer, v => swPer = v);
document.querySelectorAll("#swp button").forEach(b => b.addEventListener("click", sweepTable));
sweepTable();

// drawdown tables
(function(){
  const days = x => x == null ? "–" : x.toLocaleString("en-IN");
  const wl = w => w === "W1" ? "2015–21" : "2021–26";
  let h = `<thead><tr><th>Rule (4-book average)</th><th colspan="6" style="text-align:center">2015–21</th><th colspan="6" style="text-align:center">2021–26</th></tr><tr><th></th>` +
    ["W1", "W2"].map(() => `<th>CAGR</th><th>Worst fall</th><th>Days ≥ 10% down</th><th>Longest drawdown (days)</th><th>Ulcer</th><th>Ulcer vs random</th>`).join("") + `</tr></thead><tbody>`;
  const by = {}; D.dd.forEach(r => (by[r.config] = by[r.config] || {})[r.window] = r);
  Object.values(by).forEach(o => {
    const c = r => `<td>${pc(r.cagr)}</td><td>${pc(r.max_dd)}</td><td>${pc(r.below10, 0)}</td><td>${days(r.longest)}</td><td>${r.ulcer.toFixed(1)}</td><td ${r.pct_ulcer == null ? "" : tint(r.pct_ulcer)}>${r.pct_ulcer == null ? "–" : r.pct_ulcer.toFixed(0)}</td>`;
    h += `<tr class="${o.W1.config === "hold" ? "ref" : ""} ${o.W1.config === "triple" ? "desc" : ""}"><td class="l">${esc(o.W1.label)}</td>${c(o.W1)}${c(o.W2)}</tr>`;
  });
  $("#ddT").innerHTML = h + "</tbody>";
  $("#ddCap").textContent = `Ulcer vs random: the median across books of the share of random-timing draws (same exposure, same switches) with a higher Ulcer index; above 50 means shallower and shorter drawdowns than the same exits at random weeks. 'Any day below the last high' is not shown as a column: it is ${pc(D.uw_range[0], 0)}–${pc(D.uw_range[1], 0)} of days for every rule and for holding, because a daily NAV is almost always below its previous peak, so it does not separate the rules.`;
  $("#ddRefT").innerHTML = `<thead><tr><th>Period</th><th>Book</th><th>Days ≥ 10% down: rule</th><th>hold</th><th>Longest drawdown: rule</th><th>hold</th><th>Ulcer: rule</th><th>hold</th><th>Ulcer vs random</th></tr></thead><tbody>` +
    D.dd_ref.map(r => `<tr><td>${wl(r.window)}</td><td>${r.book.slice(-4)}</td><td class="${r.below10 <= r.h_below10 ? "pos" : "neg"}">${pc(r.below10, 0)}</td><td>${pc(r.h_below10, 0)}</td><td class="${r.longest <= r.h_longest ? "pos" : "neg"}">${days(r.longest)}</td><td>${days(r.h_longest)}</td><td class="${r.ulcer <= r.h_ulcer ? "pos" : "neg"}">${r.ulcer.toFixed(1)}</td><td>${r.h_ulcer.toFixed(1)}</td><td>${r.pct_ulcer.toFixed(0)}</td></tr>`).join("") + "</tbody>";
})();

strip(); curve();
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { strip(); curve(); }, 150); });
})();
</script>
"""

if __name__ == "__main__":
    main()
