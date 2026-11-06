# -*- coding: utf-8 -*-
"""
Build "The Overlay Casebook" — a research log covering both studies end to end.

Not a findings report. Its job is to let someone who was not in the room see what
was asked, what was found, what was got wrong and corrected, and what is still
open. The spine is that every control added made the claim smaller.

Reuses report.py's chart helpers, validated palette and typography so the two
artifacts read as one body of work.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR
from report import (
    CSS,
    FONTS,
    details,
    grouped_bars,
    legend,
    lines_chart,
    num,
    pct,
    table,
)

MAIN = EVIDENCE_DIR / "main"
SEG = EVIDENCE_DIR / "segment_v1"
BOOKS = ["SCMO_0042", "SCMO_0043", "SCMO_0044", "SCMO_0045"]
SHORT = {b: b.replace("SCMO_", "") for b in BOOKS}
PARENT = {"SCMO_0042": "0003", "SCMO_0043": "0007",
          "SCMO_0044": "0010", "SCMO_0045": "0029"}

EXTRA_CSS = """
.status{display:inline-block;font-family:var(--mono);font-size:10px;
  letter-spacing:.09em;text-transform:uppercase;padding:3px 8px;border-radius:3px;
  border:1px solid var(--border);color:var(--text-secondary);
  background:var(--band);vertical-align:middle;margin-left:10px}
.status.done{color:var(--pos);border-color:var(--pos)}
.status.open{color:var(--neg);border-color:var(--neg)}
.stepper{display:flex;flex-direction:column;gap:0;margin:24px 0;max-width:70ch}
.step{display:grid;grid-template-columns:132px 1fr;gap:18px;padding:14px 0;
  border-top:1px solid var(--border)}
.step:last-child{border-bottom:1px solid var(--border)}
.step .amt{font-family:var(--serif);font-size:23px;font-weight:500;
  line-height:1.1;letter-spacing:-.02em}
.step .amt.dn{color:var(--neg)}.step .amt.up{color:var(--pos)}
.step .amt small{display:block;font-family:var(--mono);font-size:9.5px;
  letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  margin-top:5px;font-weight:400}
.step .txt{font-size:14.5px;line-height:1.55;color:var(--text-secondary);
  align-self:center}
.step .txt b{color:var(--text-primary);font-weight:600}
.ledger td{text-align:left;white-space:normal;font-family:var(--sans);
  font-size:13px;line-height:1.5;vertical-align:top}
.ledger th{text-align:left}
.ledger td:first-child{min-width:170px;font-weight:600}
.ledger td:nth-child(2){font-family:var(--mono);font-size:11.5px;
  color:var(--text-secondary);min-width:150px}
"""


def load() -> dict:
    d = {}
    d["attr"] = pd.read_csv(MAIN / "attribution.csv")
    d["mcap"] = pd.read_csv(MAIN / "mcap_exposure.csv")
    d["gold"] = pd.read_csv(MAIN / "gold_prediction_by_signal.csv")
    d["nul"] = pd.read_csv(MAIN / "null_random_timing.csv")
    d["prank"] = pd.read_csv(MAIN / "signal_policy_ranking.csv")
    d["off"] = pd.read_csv(MAIN / "offwindow_economics.csv")
    d["eps"] = pd.read_csv(MAIN / "episode_summary.csv")

    d["head"] = pd.read_csv(SEG / "headline_before_after.csv")
    d["static"] = pd.read_csv(SEG / "static_mix_control.csv")
    d["drift"] = pd.read_csv(SEG / "spec_drift_diagnostic.csv")
    d["band"] = pd.read_csv(SEG / "band_sweep.csv")
    d["cadence"] = pd.read_csv(SEG / "index_cadence_comparison.csv")
    d["flat"] = pd.read_csv(SEG / "no_intraday_penalty.csv")
    d["bake"] = pd.read_csv(SEG / "microcap_extension_bakeoff.csv")
    d["expo"] = pd.read_csv(SEG / "exposure_profile.csv")
    d["bucket"] = pd.read_csv(SEG / "bucket_contribution.csv")
    d["clsmem"] = pd.read_csv(SEG / "classifier_vs_membership.csv")
    d["gate"] = json.loads((SEG / "gate_v2_summary.json").read_text(encoding="utf-8"))
    return d


def exposure_shares(expo: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for arm, g in expo.groupby("arm"):
        w = g["equity_weight"]
        rows.append({
            "arm": arm,
            "zero": float((w <= 1e-9).mean()),
            "partial": float(((w > 1e-9) & (w < 1 - 1e-9)).mean()),
            "full": float((w >= 1 - 1e-9).mean()),
            "avg_equity": float(w.mean()),
        })
    return pd.DataFrame(rows).set_index("arm")


def build(D: dict) -> str:
    A = D["attr"].copy()
    A["lab"] = A["aa_label"].astype(str).str.zfill(4)
    A = A.set_index("lab")
    H = D["head"][D["head"].cost_bps == 20.8].set_index("aa_scid")
    S = D["static"]
    Sg = S[S.arm == "sleeve_n100gate"].set_index("book")
    Ss = S[S.arm == "sleeve"].set_index("book")
    ex = exposure_shares(D["expo"])
    g = D["gate"]

    O: list[str] = []
    O.append("<title>The Overlay Casebook</title>")
    O.append(FONTS)
    O.append(f"<style>{CSS}{EXTRA_CSS}</style>")
    O.append('<div class="wrap">')
    O.append('<p class="eyebrow">Research casebook &middot; SCMO_0042&ndash;0045</p>')
    O.append("<h1>The Overlay Casebook</h1>")
    O.append('<p class="sub">Two studies on the same asset-allocation overlay: what was '
             "asked, what was found, what was wrong, and what is still open.</p>")
    O.append('<p class="meta">Study 1 COMPLETE &nbsp;&middot;&nbsp; Study 2 IN PROGRESS '
             "&nbsp;&middot;&nbsp; 2021-11-01 &rarr; 2026-08-21 &nbsp;&middot;&nbsp; "
             "1,186 sessions</p>")

    # ── The spine ──────────────────────────────────────────────────────────
    O.append('<p class="lede">One pattern runs through all of it: <strong>every control '
             "we added made the claim smaller.</strong> Nothing here was overturned by "
             "an outside objection &mdash; each reduction came from a test we chose to "
             "run. That is the most useful thing to take from this document, and it is "
             "why the open items at the end matter more than the headline numbers.</p>")

    gate_tot = float(Sg["total_vs_parent"].mean())
    gate_static = float(Sg["static_vs_parent"].mean())
    gate_timing = float(Sg["timing_pp"].mean())
    O.append('<div class="stepper">')
    for amt, cls, role, txt in [
        ("&ldquo;All four<br>outperformed&rdquo;", "", "the brief",
         "<b>Where it started.</b> Explain the outperformance of the four AA "
         "smallcases against their parents."),
        ("2 of 4", "dn", "cut to",
         "<b>First finding, first deflation.</b> The overlay <i>added</i> 5.8 and 7.1 "
         "points a year to 0042/0043 and <i>cost</i> 0044/0045 4.5 and 3.7. The "
         "question changed from &ldquo;why did it work?&rdquo; to &ldquo;when does it "
         "pay?&rdquo;"),
        ("84%", "dn", "cause reassigned",
         "<b>It was the asset, not the timing.</b> Gold supplied 84% of everything the "
         "defensive sleeve earned. Swap gold for cash and every positive result "
         "collapses."),
        ("z &le; 1.01", "dn", "not significant",
         "<b>And the timing never cleared a null.</b> Against episodes relocated at "
         "random, no book beat the noise. The MDE was around +100% cumulative "
         "value-add &mdash; this history cannot distinguish skill from luck."),
        (f"+{gate_tot:.2f}pp", "up", "study 2 opens",
         "<b>A genuinely better rule appears.</b> Segment-level selection plus a "
         "large-cap gate beats the parent on all four books at every cost level, and "
         "flips both books the old overlay had damaged."),
        (f"+{gate_timing:.2f}pp", "dn", "deflated to",
         f"<b>Then the static-mix control.</b> Of that {gate_tot:.2f}pp, "
         f"{gate_static:+.2f}pp is just holding a sleeve that out-returned equity by "
         "~4.8pp/yr. Only the remainder is timing &mdash; though see the per-book "
         "split below, which cuts the other way."),
        ("?", "", "pending",
         "<b>And one control is still outstanding.</b> A plain large-cap regime filter "
         "with <i>no segment selection at all</i> may capture most of what is left. "
         "Until that runs, the segment mechanic is unproven."),
    ]:
        O.append(f'<div class="step"><div class="amt {cls}">{amt}'
                 f"<small>{role}</small></div>"
                 f'<div class="txt">{txt}</div></div>')
    O.append("</div>")

    # ── Study 1 ────────────────────────────────────────────────────────────
    O.append('<h2>Study 1 &mdash; Where the overlay\'s returns came from'
             '<span class="status done">complete</span></h2>')
    O.append("<p>The AA version holds <em>exactly</em> its parent when risk-on, so the "
             "difference between them is earned only on the days they differ. In log "
             "space that split is additive and therefore exact &mdash; it reconciles to "
             "~1e-17, with no residual:</p>")
    O.append('<div class="formula">log(AA) &minus; log(parent)<br>'
             "&nbsp;&nbsp;= &Sigma;<sub>risk-on</sub> excess &nbsp;&rarr;&nbsp; TRACKING"
             "<br>&nbsp;&nbsp;+ &Sigma;<sub>risk-off</sub> excess &nbsp;&rarr;&nbsp; "
             "TIMING</div>")

    cats = ["0042", "0043", "0044", "0045"]
    O.append('<div class="card">')
    O.append(legend([("Tracking (risk-on)", "s3"), ("Timing (risk-off)", "s4")]))
    O.append(grouped_bars(
        cats,
        {"Tracking": [A.loc[c, "tracking_ann"] for c in cats],
         "Timing": [A.loc[c, "timing_ann"] for c in cats]},
        fmt=lambda v: pct(v, 1, True), ylab="Contribution p.a.", height=290,
        colors=["s3", "s4"],
    ))
    O.append('<p class="cap">Two books gained, two lost &mdash; and for different '
             "reasons. 0044 lost mostly to tracking, 0045 almost entirely to timing.</p>")
    O.append("</div>")

    O.append("<p><strong>Tracking should have been zero</strong> &mdash; while both are "
             "in equities they hold the same basket. It was not. The cause turned out to "
             "be narrower than a general drift: the parents reconstitute quarterly, and "
             "the AA books intermittently <em>failed to adopt a reconstitution</em>. On "
             "2022-09-15 parent 0010 rotated six of fifteen names and 0044 kept the old "
             "six until end-October &mdash; 40% of the book wrong for ten weeks. All "
             "four desynchronised first on the same date. That is an operational defect, "
             "not a property of the strategy.</p>")

    O.append("<h3>The overlay helped exactly where the stock picking was bad</h3>")
    M = D["mcap"].copy()
    M["lab"] = M["parent_label"].astype(str).str.zfill(4)
    O.append(table(M, [
        ("lab", "Parent", None),
        ("w_nifty100", "N100", lambda v: pct(v, 0)),
        ("w_midcap150", "MC150", lambda v: pct(v, 0)),
        ("w_smallcap250", "SC250", lambda v: pct(v, 0)),
        ("w_microcap250", "Micro250", lambda v: pct(v, 0)),
        ("selection_alpha_ann", "Selection alpha", lambda v: pct(v, 1, True)),
    ]))
    O.append("<p>Selection alpha runs almost perfectly <em>inverse</em> to the overlay's "
             "value: 0007 gave up 7.7 points a year against its own market-cap blend and "
             "gained most from the overlay; 0010 and 0029 beat theirs and were hurt by "
             "it. That is the signature of a blunt de-risking rule, not a timing rule "
             "&mdash; and it is the observation that motivated Study 2.</p>")

    O.append("<h3>While out of equity, equity mostly went up</h3>")
    OW = D["off"].copy()
    OW["lab"] = OW["aa_label"].astype(str).str.zfill(4)
    O.append(table(OW, [
        ("lab", "AA", None),
        ("off_sessions", "Sessions out", None),
        ("parent_return_while_out", "Parent did", lambda v: pct(v, 1, True)),
        ("actual_sleeve_return_while_out", "Sleeve did", lambda v: pct(v, 1, True)),
        ("gold_return_while_out", "Gold did", lambda v: pct(v, 1, True)),
        ("cash_return_while_out", "Cash did", lambda v: pct(v, 1, True)),
    ]))
    O.append('<div class="callout warn"><p>This is the table that reframed the study. '
             "The switch did not, in general, dodge a fall &mdash; in three of four "
             "cases the parent <em>rose</em> while the book sat out of it. It earned a "
             "better asset instead, because gold nearly doubled. Strip gold out and the "
             "edge goes with it.</p></div>")

    O.append("<h3>Which trend predicts gold: monotonic in market cap</h3>")
    GP = D["gold"].copy()
    lab = {"nifty50": "N50", "nifty100": "N100", "nifty500_synth": "N500*",
           "midcap100": "MC100", "midcap150": "MC150", "smallcap100": "SC100",
           "smallcap250": "SC250", "microcap250": "Micro250"}
    GP["lab"] = GP["signal"].map(lab).fillna(GP["signal"])
    GP = GP.sort_values("edge_pp", ascending=False)
    O.append('<div class="card">')
    O.append(grouped_bars(
        list(GP["lab"]), {"edge": list(GP["edge_pp"] / 100.0)},
        fmt=lambda v: pct(v, 0, True), color_by_sign=True, width=820, height=280,
        ylab="Gold's excess return p.a. while that signal is defensive",
    ))
    O.append('<p class="cap">Perfectly ordered by market cap. The smaller the companies '
             "whose trend you follow, the better it marks gold's good periods &mdash; "
             "and a broad cap-weighted index (N500*) lands at the 50th percentile, no "
             "better than random.</p>")
    O.append("</div>")
    O.append("<p>Two conclusions followed. Going <em>broader</em> is not the answer: "
             "Nifty 500 is ~76% Nifty 100 by weight, so its trend is a large-cap trend. "
             "And requiring two indices to agree beat every single index &mdash; "
             "<strong>Nifty 100 AND Smallcap 100</strong> averaged +10.6%/yr and won on "
             "all four books, while signalling off each book's own largest bucket "
             "averaged +3.0 to +4.9 and was worse than what was already running.</p>")

    O.append(details("Study 1 &mdash; significance testing, in full", table(D["nul"], [
        ("aa_label", "AA", lambda v: str(v).zfill(4)),
        ("observed_value_add_return", "Observed", lambda v: pct(v, 1, True)),
        ("null_mean_return", "Null mean", lambda v: pct(v, 1, True)),
        ("percentile", "Percentile", lambda v: f"{v*100:.0f}th"),
        ("z_vs_null", "z", lambda v: num(v, 2)),
        ("null_sd_over_observed_sd", "null sd / obs sd", lambda v: num(v, 2)),
        ("mde_return", "MDE", lambda v: pct(v, 0, True)),
    ])))

    # ── Study 2 ────────────────────────────────────────────────────────────
    O.append('<h2>Study 2 &mdash; Segment-level selection'
             '<span class="status open">in progress</span></h2>')
    O.append("<p>If the overlay is blunt, the obvious fix is to stop flipping the whole "
             "book. Classify each holding into a market-cap bucket, hold the stocks "
             "whose <em>own</em> bucket is trending, and send the rest to the sleeve. "
             "Three arms were built: <code>sleeve</code> (freed weight to gold+cash), "
             "<code>rotate</code> (freed weight redistributed, stays in equity), and "
             "<code>sleeve_n100gate</code> (also requires Nifty 100 to be trending).</p>")

    O.append("<h3>Getting a trustworthy classifier was most of the work</h3>")
    O.append("<p>Point-in-time classification was the binding constraint. The membership "
             "table holds only five snapshots, all from 2026 &mdash; using it would tag "
             "2022 holdings with 2026 membership, mis-tagging precisely the stocks that "
             "changed size. That bias sits directly on the mechanism being tested. It "
             "was resolved by finding a market-cap table carrying 412 snapshot dates "
             "back to 2005 &mdash; every month from 2021-01 to 2026-08 present &mdash; "
             "then validating the rank-band proxy against production's own bucket "
             "output rather than assuming it.</p>")
    CM = D["clsmem"].groupby("classifier").last().reset_index()
    O.append(table(CM, [
        ("classifier", "Classifier", None),
        ("agree_3bucket", "vs membership, 3-bucket", lambda v: pct(v, 1)),
        ("agree_4bucket", "vs membership, 4-bucket", lambda v: pct(v, 1)),
        ("recall_Largecap", "Large recall", lambda v: pct(v, 1)),
        ("recall_Smallcap", "Small recall", lambda v: pct(v, 1)),
        ("recall_Microcap", "Micro recall", lambda v: pct(v, 1)),
    ]))
    O.append("<p>Semi-annual ranking on NSE's own methodology beat naive monthly "
             "re-ranking by ~6 points, so it became the default. Unmappable holdings "
             "fell from 12&ndash;33% a year to under 2%.</p>")
    O.append(details("The Microcap band had to be widened &mdash; band sweep",
                     table(D["band"], [
                         ("band", "Band", None),
                         ("precision_Microcap", "Micro precision", lambda v: pct(v, 1)),
                         ("recall_Microcap", "Micro recall", lambda v: pct(v, 1)),
                         ("f1_Microcap", "Micro F1", lambda v: num(v, 3)),
                         ("accuracy_4bucket_members", "4-bucket acc", lambda v: pct(v, 1)),
                         ("unknown_share", "Unknown share", lambda v: pct(v, 1)),
                     ])))
    O.append("<p>Nifty Microcap 250 draws from beyond rank 750 &mdash; 62 of its 250 "
             "members sit outside the original band &mdash; so <code>501&ndash;750</code> "
             "was mis-specified rather than merely noisy. Widening to "
             "<code>501&ndash;900</code> lifted microcap recall from 68% to 92%.</p>")

    O.append("<h3>The gate passed, and found spec drift on the way</h3>")
    O.append("<p>Reproducing production's own intermediates &mdash; its bucket "
             f"distribution and signal score across {g['fridays']} Fridays and "
             f"{g['books']} books &mdash; matched at "
             f"<strong>{g['mcat_dist_match']*100:.0f}%</strong> "
             f"(max abs error {g['max_abs_err_lcap']:.1e}) with the signal score exact. "
             "Three corrections were needed to get there, and each is a finding.</p>")
    O.append("<ul>")
    O.append("<li><strong>The signal input set is not constant.</strong> Production's "
             "own log shows it computing the score from "
             "<code>Nifty100 | MC100 | SC100</code> until 2026-04-17, then switching to "
             "<code>Nifty100 | Midcap150 | Smallcap250</code> on 2026-04-24.</li>")
    O.append("<li><strong>The rebalance history is not always what production ran "
             f"on.</strong> On {g['weeks_history_basket_disagreed']} book-weeks it held "
             "a basket differing from any row in the history file &mdash; adopting a "
             "reconstitution early, then reverting. The same defect class Study 1 "
             "found.</li>")
    O.append(f"<li><strong>{g['untestable_rows']} rows are untestable, not "
             "failing</strong> &mdash; they predate the first membership snapshot, so "
             "production's own classification source no longer exists.</li>")
    O.append("</ul>")

    DR = D["drift"].groupby("year")[["match_sc250", "match_sc100"]].mean()
    yrs = list(DR.index)
    O.append('<div class="card">')
    O.append(legend([("v2's rule (Smallcap 250)", "s1"),
                     ("earlier rule (Smallcap 100)", "s2")]))
    O.append(lines_chart(
        [float(y) for y in yrs],
        {"SC250": list(DR["match_sc250"]), "SC100": list(DR["match_sc100"])},
        fmt=lambda v: pct(v, 0), xlab="Year", height=300,
        ylab="Agreement with the realized live states",
    ))
    O.append('<p class="cap">Mean across the four books. The live track record was '
             "produced by the Smallcap 100 rule (98.9% overall), not by the Smallcap "
             "250 rule in production today (89.9%).</p>")
    O.append("</div>")
    O.append('<div class="callout"><p>This matters beyond bookkeeping. It means the '
             "published track record and any backtest of the current engine are not "
             "measuring the same strategy, and it retroactively explains why Study 1 "
             "found two books reconciling as pure Smallcap 100 rules. The gate was "
             "redefined around production's own intermediates precisely because "
             "reproducing history was unachievable.</p></div>")

    O.append("<h3>The headline &mdash; and immediately, the deflation</h3>")
    O.append('<div class="card">')
    O.append(legend([("production v2", "s1"), ("sleeve", "s2"),
                     ("rotate", "s3"), ("sleeve + N100 gate", "s4")]))
    O.append(grouped_bars(
        cats,
        {"production_v2": [H.loc[b, "production_v2_vs_parent"] for b in BOOKS],
         "sleeve": [H.loc[b, "sleeve_vs_parent"] for b in BOOKS],
         "rotate": [H.loc[b, "rotate_vs_parent"] for b in BOOKS],
         "gate": [H.loc[b, "sleeve_n100gate_vs_parent"] for b in BOOKS]},
        fmt=lambda v: pct(v, 0, True), ylab="Excess over parent p.a., net @ 20.8bps",
        width=820, height=310,
    ))
    O.append('<p class="cap">The hypothesis held: segment selection flips 0044 and 0045 '
             "from negative to positive, and the gate arm wins on all four books at "
             "every cost level. <code>rotate</code> is the weakest arm.</p>")
    O.append("</div>")

    O.append("<p>But the sleeve returned <strong>17.98%/yr</strong> over this window "
             "against parents averaging 13.20%. A defensive asset out-returning equity "
             "means any rule that sits in it more wins mechanically, so the static-mix "
             "control &mdash; each arm's average equity share held constant, no timing "
             "at all &mdash; was run immediately rather than deferred:</p>")
    O.append('<div class="card">')
    O.append(legend([("Static mix (mechanical)", "s1"), ("Timing", "s4")]))
    O.append(grouped_bars(
        cats,
        {"Static": [Sg.loc[b, "static_vs_parent"] / 100.0 for b in BOOKS],
         "Timing": [Sg.loc[b, "timing_pp"] / 100.0 for b in BOOKS]},
        fmt=lambda v: pct(v, 1, True), ylab="Decomposition of the gate arm's excess",
        height=300, colors=["s1", "s4"],
    ))
    O.append('<p class="cap">Gate arm only. Mean across books: '
             f"{gate_static:+.2f}pp mechanical, {gate_timing:+.2f}pp timing.</p>")
    O.append("</div>")
    O.append('<div class="callout"><p><strong>The per-book split is more interesting '
             "than the average, and it cuts the other way.</strong> The mechanical "
             "component is huge for 0043 (+6.54pp, whose parent returned only 6.2%) but "
             "<em>negative</em> for 0044 (&minus;0.28pp, whose parent returned 20.3%). "
             "So for 0044 &mdash; the book whose flip is the whole point of Study 2 "
             "&mdash; essentially all of the +5.52pp is timing, not sleeve exposure. "
             "&ldquo;Most of the headline is mechanical&rdquo; is true on average and "
             "false where it matters most.</p></div>")
    O.append(details("Static-mix control, every book and arm", table(S, [
        ("book", "Book", lambda v: str(v).replace("SCMO_", "")),
        ("arm", "Arm", None),
        ("avg_eq", "Avg equity", lambda v: f"{v:.1f}%"),
        ("parent_cagr", "Parent CAGR", lambda v: f"{v:.2f}%"),
        ("arm_cagr", "Arm CAGR", lambda v: f"{v:.2f}%"),
        ("static_vs_parent", "Static vs parent", lambda v: f"{v:+.2f}pp"),
        ("timing_pp", "Timing", lambda v: f"{v:+.2f}pp"),
        ("total_vs_parent", "Total", lambda v: f"{v:+.2f}pp"),
    ])))

    O.append("<h3>The structural claim is weaker than we assumed</h3>")
    O.append("<p>Segment selection was supposed to rarely sit at either extreme. It "
             "does so less than an all-or-nothing rule &mdash; but not much less:</p>")
    ex2 = ex.reset_index()
    O.append(table(ex2, [
        ("arm", "Arm", None),
        ("zero", "0% equity", lambda v: pct(v, 1)),
        ("partial", "Partial", lambda v: pct(v, 1)),
        ("full", "100% equity", lambda v: pct(v, 1)),
        ("avg_equity", "Avg equity", lambda v: pct(v, 1)),
    ]))
    BK = D["bucket"][D["bucket"].arm == "sleeve"].groupby("bucket")["hold_rate"].mean()
    O.append("<p>The reason is in the hold rates, which are near-identical across "
             "buckets &mdash; "
             + ", ".join(f"{k} {v:.1%}" for k, v in BK.items() if k != "ETF")
             + " &mdash; because the bucket signals move together. The same fact made "
             "the dedicated-microcap-signal variant differ from the production "
             "convention on only 2% of weeks, which is why that arm was demoted to a "
             "sensitivity. <strong>The actionable size distinction in this data is "
             "small-versus-large, not micro-versus-small.</strong></p>")

    # ── Corrections ledger ─────────────────────────────────────────────────
    O.append('<h2>Corrections ledger</h2>')
    O.append("<p>Six substantive errors were found and fixed across the two studies. "
             "This is the section that should calibrate how much weight to put on "
             "everything above &mdash; both because the errors were material, and "
             "because they were found by controls rather than by readers.</p>")
    led = pd.DataFrame([
        {"what": "LIQUIDBEES priced at zero return",
         "sz": "Cash leg credited with nothing",
         "detail": "The fund holds a constant NAV and distributes its yield, so its "
                   "price history returns exactly 0.00% over any window. Fixed with a "
                   "dividend-reinvested series: +4.99%/yr over the window."},
        {"what": "Microcap omitted from the factor set",
         "sz": "Selection alpha overstated 2–5pp/yr",
         "detail": "The blend regression offered only Nifty 100 / Midcap 150 / Smallcap "
                   "250, so genuine microcap exposure was forced onto the nearest "
                   "factor. Parent 0003 read 93% smallcap without it and 58% microcap "
                   "with it. Microcap also compounded fastest, so every benchmark was "
                   "understated."},
        {"what": "Tracking drift attributed to the wrong cause",
         "sz": "Mechanism wrong, magnitude right",
         "detail": "Reported as the AA book going stale against a parent that "
                   "reconstitutes more often. The parents reconstitute quarterly and the "
                   "books match on 97–98% of holdings. The real cause was specific "
                   "missed reconstitutions — an operational defect, and a cheaper "
                   "fix."},
        {"what": "A signal-agreement bar set too high to reach",
         "sz": "Would have read as a failed test",
         "detail": "A 97% bar was set by analogy to a check whose series had intraday "
                   "range. A series built from daily closes has none: weekly true range "
                   "shrinks ~26%, bands narrow, the latch flips more. ~10 of the ~13 "
                   "points of shortfall were pure artifact."},
        {"what": "simulate() re-trimmed to target every week",
         "sz": "−1.18pp → −0.34pp on the parent leg",
         "detail": "Manufactured turnover in every held name and suppressed "
                   "within-period weight drift. Rebalancing only when the target "
                   "actually changes closed most of the gap against the published "
                   "parent series."},
        {"what": "Audit counters triple-counted",
         "sz": "Every handling event reported 3×",
         "detail": "The simulator runs once per cost level into a shared counter, so all "
                   "data-handling events were inflated by the number of cost levels."},
    ])
    O.append(table(led, [
        ("what", "Error", None),
        ("sz", "Effect", None),
        ("detail", "What happened", None),
    ], cls="ledger"))
    O.append("<p>Two further items are limitations rather than errors, and both remain "
             "live: the window contains a single uninterrupted gold bull market, and the "
             "published NAV carries two known divergences from any backtest of the "
             "current engine &mdash; the equity-leg desync and the spec drift above.</p>")

    # ── Open ───────────────────────────────────────────────────────────────
    O.append('<h2>Still open<span class="status open">provisional</span></h2>')
    O.append('<div class="callout warn"><p><strong>Study 2\'s headline should not be '
             "cited as settled.</strong> One outstanding control can materially deflate "
             "it, and it has been pre-registered precisely so the conclusion cannot "
             "drift to fit the number once it exists.</p></div>")
    O.append("<ol>")
    O.append("<li><strong>The <code>n100_only</code> control.</strong> Hold the whole "
             "parent when Nifty 100 is trending and the sleeve when it is not, with no "
             "bucket selection at all. Nifty 100's hold rate is 59.9% and the gate arm "
             f"is {ex.loc['sleeve_n100gate','zero']:.0%} fully defensive, so the exposure "
             "profiles are nearly identical &mdash; a plain regime filter may capture "
             "most of the edge. <b>Pre-registered:</b> if it captures &ge;70%, the "
             "finding becomes &ldquo;a large-cap regime filter works&rdquo; and the "
             "segment mechanic is reported as <em>not proven</em>.</li>")
    O.append("<li><strong>The all-cash sleeve.</strong> Cash returned ~4.99%/yr against "
             "the sleeve's 17.98%, so a 30% allocation swings from roughly +2.0pp of "
             "tailwind to &minus;2.5pp of drag. The static component reverses sign and "
             "the arm ranking may invert, with the most defensive arm hurt worst. "
             "Actual-sleeve and all-cash will be reported as co-equal headlines.</li>")
    O.append("<li><strong>A null on the timing term.</strong> The "
             f"{gate_timing:+.2f}pp still has no null beside it. Because the bucket "
             "signals move together, permuting <em>which</em> bucket is trending is "
             "low-powered; the primary null block-relocates the whole signal panel in "
             "time instead.</li>")
    O.append("<li><strong>Classifier distribution uncertainty.</strong> The gate "
             "validated the <em>formula</em> using production's own classification. Our "
             "point-in-time classifier reproduces production's exact bucket distribution "
             f"on only <strong>{g['pit_classifier_mcat_dist_match']*100:.0f}%</strong> of "
             "book-weeks &mdash; per-holding accuracy is 95.7%, but the aggregate that "
             "actually feeds the signal score diverges more often. The arms rest on that "
             "classifier.</li>")
    O.append("<li><strong>Two unpriceable names.</strong> EQUITAS and SHRIRAMCIT are "
             "pre-merger entities with no rows in the price table, at 13.3% weight of "
             "one 0010 rebalance &mdash; and 0010's flip is the headline. That flip needs "
             "confirming without them.</li>")
    O.append("</ol>")

    O.append("<hr>")
    O.append('<p class="fine">Study 1 is complete: code in <code>AA/analysis/</code>, '
             "evidence in <code>evidence/main/</code>, report published separately as "
             "&ldquo;Gold, Not Timing&rdquo;. Study 2 is in progress: "
             "<code>evidence/segment_v1/</code>. Conventions throughout: Sharpe is "
             "CAGR/volatility at a zero risk-free rate; costs are round-trip, half per "
             "side, reported at 0 / 20.8 / 50 bps; point-in-time is asserted rather than "
             "assumed, with assertion and violation counts in <code>audit.json</code>; "
             "and every return is reported against a null where one exists.</p>")
    O.append("</div>")
    return "\n".join(O)


def main() -> None:
    D = load()
    html = build(D)
    out = Path(SEG / "casebook.html")
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
