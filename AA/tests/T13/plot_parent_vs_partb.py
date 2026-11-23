"""T13 extra charts (forked from T11's): hold-the-parent against the 2-of-3 rule, per smallcase, 2014-09-01 -> 2019-01-02, for every variant of the rule and cost.

    python tests/T13/plot_parent_vs_partb.py                                   (headline: reads evidence/headline, writes evidence/plots)
    python tests/T13/plot_parent_vs_partb.py --evidence DIR [--out DIR] [--books SCMO_0003]   (another evidence directory; --out defaults to DIR/../plots,
                                                                                the folder report.py looks in)

Reads only daily_nav.csv of the evidence directory (T13's own output; rebuilt NAVs, not validated against a published NAV before 2019-01-02).
The rule is T13's: hold the parent when at least two of the three weekly index signals are BUY. T11's all-3 rule (runs strategy_all3*) is not plotted here; the page draws it.
Variants: Part B = run `strategy` (sleeve timed by MAUc1) and Part A = run `strategy_fixed50` (sleeve fixed 50/50), each at 0, 20.8 and 50 bps round trip,
each against `hold_parent` at the SAME cost. Both lines are rebased to index 100 on 2014-09-01's close. The third line, on the RIGHT axis, is
    outperformance = index of parent - index of the rule      (index points; positive = holding the parent was ahead)
Writes <out>/parent_vs_part{a,b}_{cost}bps.png (six charts) and parent_vs_rule_all_variants.csv (every plotted series).
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt    # noqa: E402
import pandas as pd                # noqa: E402

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--evidence", default=str(HERE / "evidence" / "headline"))
ap.add_argument("--out", default=None, help="default: the evidence directory's sibling 'plots' (where report.py looks)")
ap.add_argument("--books", default=None, help="comma list; for evidence directories that hold fewer than the four books")
args = ap.parse_args()
SRC = Path(args.evidence) / "daily_nav.csv"
OUT = Path(args.out) if args.out else Path(args.evidence).parent / "plots"
OUT.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, GREY = "#0072B2", "#D55E00", "#444444"      # Okabe-Ito blue and vermillion; neutral grey for the gap (right axis)
INK, MUTED, GRID = "#1a1a1a", "#666666", "#e6e6e6"
BOOKS = args.books.split(",") if args.books else ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
PARTS = {"B": ("strategy", "Part B: 2-of-3 rule with MAUc1-timed sleeve"), "A": ("strategy_fixed50", "Part A: 2-of-3 rule with fixed 50/50 sleeve")}
COSTS = [0.0, 20.8, 50.0]

d = pd.read_csv(SRC, parse_dates=["date"])
d = d[d["run"].isin(["hold_parent", "strategy", "strategy_fixed50"])]
allrows = []
for part, (run, label) in PARTS.items():
    for cost in COSTS:
        fig, axes = plt.subplots(2, 2, figsize=(15, 9.2), sharex=True, squeeze=False)
        fig.patch.set_facecolor("white")
        axes2 = []
        for ax, b in zip(axes.ravel(), BOOKS):
            sel = d[(d["book"] == b) & (d["cost_bps"] == cost)]
            par = sel[sel["run"] == "hold_parent"].set_index("date")["nav"].sort_index()
            rul = sel[sel["run"] == run].set_index("date")["nav"].sort_index()
            assert par.index.equals(rul.index) and len(par) > 1000, (b, cost, part)
            parent, rule = 100 * par, 100 * rul
            gap = parent - rule                              # index of parent - index of the rule
            allrows.append(pd.DataFrame({"part": part, "cost_bps": cost, "book": b, "date": parent.index.strftime("%Y-%m-%d"),
                                         "index_parent": parent.values, "index_rule": rule.values, "outperformance": gap.values}))
            ax.set_facecolor("white")
            ax.plot(parent.index, parent, color=BLUE, lw=1.6, label="Hold the parent (index, left axis)")
            ax.plot(rule.index, rule, color=ORANGE, lw=1.6, label=f"{label} (index, left axis)")
            ax.set_ylabel("Index (100 = 2014-09-01)", color=INK, fontsize=9)
            ax.grid(True, color=GRID, lw=0.8)
            ax.set_axisbelow(True)
            ax2 = ax.twinx()                                 # the gap line has its own scale, on the right
            axes2.append(ax2)
            ax2.plot(gap.index, gap, color=GREY, lw=1.4, ls="--", label="Outperformance: parent minus rule (index points, right axis)")
            ax2.fill_between(gap.index, 0, gap, color=GREY, alpha=0.10, lw=0)
            ax2.axhline(0, color=GREY, lw=0.8, alpha=0.6)
            ax2.set_ylabel("Parent index minus rule index (points)", color=GREY, fontsize=9)
            ax2.tick_params(axis="y", colors=GREY, labelsize=8)
            ax.spines["top"].set_visible(False); ax2.spines["top"].set_visible(False)
            ax.tick_params(axis="both", labelsize=8)
            ax.set_title(f"{b}   (end: parent {parent.iloc[-1]:.0f}, rule {rule.iloc[-1]:.0f}, gap {gap.iloc[-1]:+.0f})", fontsize=10.5, color=INK, loc="left")
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        h1, l1 = axes[0, 0].get_legend_handles_labels()
        h2, l2 = axes2[0].get_legend_handles_labels()
        fig.legend(h1 + h2, l1 + l2, loc="upper center", ncol=3, frameon=False, fontsize=9.5, bbox_to_anchor=(0.5, 0.965))
        fig.suptitle(f"Hold the parent against {label.split(':')[0]}, 2014-09-01 to 2019-01-02, {cost:g} bps round-trip cost", fontsize=13, color=INK, y=0.995)
        fig.text(0.5, 0.008, "Rebuilt from the parents' baskets and Eikon prices; not validated against a published NAV before 2019-01-02. Rule: hold the parent when at least two of the three index signals are BUY. Gap = index of parent minus index of the rule (right axis, its own scale).",
                 ha="center", fontsize=8.5, color=MUTED)
        fig.tight_layout(rect=(0, 0.03, 1, 0.93))
        png = OUT / f"parent_vs_part{part.lower()}_{cost:g}bps.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        print("wrote", png.name)
allr = pd.concat(allrows)
allr.to_csv(OUT / "parent_vs_rule_all_variants.csv", index=False)
print("\nEnd of window (2019-01-02), index points, 100 = 2014-09-01:  parent / rule / gap")
for part in PARTS:
    for cost in COSTS:
        s = allr[(allr["part"] == part) & (allr["cost_bps"] == cost)]
        line = "  ".join(f"{b[-4:]}: {r.iloc[-1]['index_parent']:.0f}/{r.iloc[-1]['index_rule']:.0f}/{r.iloc[-1]['outperformance']:+.0f}" for b, r in s.groupby("book"))
        print(f"Part {part} {cost:>4g} bps  {line}")
