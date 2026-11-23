"""Everything tested on 2011-11-25 -> 2019-01-02 in one place (T09 headline evidence + the two descriptive add-ons). Descriptive only: no nulls for the add-ons, no verdicts.
Reads: tests/T09/evidence/headline/{stats,daily_nav}.csv, extra/sc100_rule_*.csv, extra/index_rule_*.csv.  Writes extra/combined_*.
Run from AA/:  python tests/T09/extra/combined_pre2019.py"""
from pathlib import Path
import numpy as np, pandas as pd
AA = Path(__file__).resolve().parents[3]
HL = AA / "tests" / "T09" / "evidence" / "headline"
X = Path(__file__).parent
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]

# name, group, source key in the NAV table / stats
LABEL = {
    "threeindex_timed": ("Three-index switch, MAUc1-timed sleeve (T09 Part B)", "rule"),
    "threeindex_fixed50": ("Three-index switch, 50/50 sleeve (T09 Part A)", "rule"),
    "sc100_timed": ("Smallcap 100 switch, MAUc1-timed sleeve", "rule"),
    "sc100_fixed50": ("Smallcap 100 switch, 50/50 sleeve", "rule"),
    "index_rule_timed": ("Per-index rule, MAUc1-timed sleeve", "rule"),
    "index_rule_fixed50": ("Per-index rule, 50/50 sleeve", "rule"),
    "hold_proxy": ("Hold the proxy portfolio (always invested)", "reference"),
    "constant_mix": ("Constant mix at the rule's average share, 50/50 non-proxy", "reference"),
    "constant_mix_timed": ("Constant mix, MAUc1-timed non-proxy", "reference"),
    "sleeve_only": ("50/50 GOLDBEES + cash only", "reference"),
    "sleeve_only_timed": ("MAUc1-timed GOLDBEES + cash only", "reference"),
    "nifty100_alone": ("Nifty 100 alone", "reference"),
    "midcap100_alone": ("Midcap 100 alone", "reference"),
    "smallcap100_alone": ("Smallcap 100 alone", "reference"),
}
# ---- stats (every cost) ----
hs = pd.read_csv(HL / "stats.csv")
hs = hs[(hs.window == "full") & (hs.cash == "lbes")]
hmap = {"strategy": "threeindex_timed", "strategy_fixed50": "threeindex_fixed50", "hold_proxy": "hold_proxy", "constant_mix": "constant_mix", "constant_mix_timed": "constant_mix_timed",
        "sleeve_only": "sleeve_only", "sleeve_only_timed": "sleeve_only_timed", "index_Nifty100": "nifty100_alone", "index_MC100": "midcap100_alone", "index_SC100": "smallcap100_alone"}
hs = hs[hs.kind.isin(hmap)].assign(run=lambda d: d.kind.map(hmap))
cols = ["book", "run", "cost_bps", "end_nav", "cagr", "max_dd", "vol", "calmar", "trades", "cost_paid"]
st = pd.concat([hs[cols], pd.read_csv(X / "sc100_rule_stats.csv")[cols], pd.read_csv(X / "index_rule_stats.csv")[cols]], ignore_index=True)
st["name"] = st.run.map(lambda r: LABEL[r][0])
st["group"] = st.run.map(lambda r: LABEL[r][1])
order = list(LABEL)
st["o"] = st.run.map(order.index)
st = st.sort_values(["book", "cost_bps", "o"]).drop(columns="o")
st[["book", "group", "run", "name", "cost_bps", "end_nav", "cagr", "max_dd", "vol", "calmar", "trades", "cost_paid"]].to_csv(X / "combined_stats.csv", index=False)

# ---- daily NAV at 20.8 ----
dn = pd.read_csv(HL / "daily_nav.csv")
dn = dn[dn.cost_bps == 20.8]
dn["run"] = dn.run.map(hmap)
dn = dn.dropna(subset=["run"])
ex = pd.read_csv(X / "index_rule_daily_nav.csv")
exl = ex.melt(id_vars=["book", "date"], value_vars=["sc100_fixed50", "sc100_timed", "index_rule_fixed50", "index_rule_timed"], var_name="run", value_name="nav")
nav = pd.concat([dn[["book", "date", "run", "nav"]], exl], ignore_index=True)
wide = nav.pivot_table(index=["book", "date"], columns="run", values="nav")[order].reset_index()
wide.to_csv(X / "combined_daily_nav_20.8bps.csv", index=False)
wide["date"] = pd.to_datetime(wide["date"])

# ---- calendar-year returns at 20.8 ----
rows = []
for b in BOOKS:
    w = wide[wide.book == b].set_index("date")[order]
    ye = w.groupby(w.index.year).last()
    first = w.iloc[[0]]
    prev = pd.concat([first, ye.iloc[:-1]])
    prev.index = ye.index
    r = ye / prev.values - 1
    r.insert(0, "book", b)
    r.index.name = "year"
    rows.append(r.reset_index())
pd.concat(rows).to_csv(X / "combined_yearly_returns_20.8bps.csv", index=False)

# ---- table at 20.8 ----
t = st[st.cost_bps == 20.8].copy()
for b in BOOKS:
    x = t[t.book == b]
    print(f"\n{b} (20.8 bps, 2011-11-25 -> 2019-01-02)")
    print(x.assign(cagr=(x.cagr * 100).round(2), max_dd=(x.max_dd * 100).round(1), vol=(x.vol * 100).round(1), calmar=x.calmar.round(2), end_nav=x.end_nav.round(2))
          [["name", "cagr", "max_dd", "vol", "calmar", "end_nav", "trades"]].to_string(index=False))

# ---- charts ----
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
COL = {"threeindex_timed": "#1f4fd8", "threeindex_fixed50": "#8fb0ee", "sc100_timed": "#2e9e6b", "sc100_fixed50": "#9fd8b8", "index_rule_timed": "#d9541e", "index_rule_fixed50": "#f0b08a",
       "hold_proxy": "#555555", "constant_mix": "#b8860b", "constant_mix_timed": "#e6c35c", "sleeve_only": "#2a8a6a", "sleeve_only_timed": "#79c9a8",
       "nifty100_alone": "#a02c8c", "midcap100_alone": "#d98ad0", "smallcap100_alone": "#6a2a6a"}
TICKS = [0.8, 1, 1.5, 2, 3, 4]


def panel(keys, fname, title, w_hi=()):
    fig, axs = plt.subplots(2, 2, figsize=(16, 10))
    for ax, b in zip(axs.ravel(), BOOKS):
        w = wide[wide.book == b]
        for k in keys:
            ax.plot(w.date, w[k], color=COL[k], lw=2.4 if k in w_hi else 1.3, label=LABEL[k][0], ls="--" if LABEL[k][1] == "reference" else "-")
        ax.set_yscale("log")
        ax.set_yticks(TICKS)
        ax.set_yticklabels([f"{x:g}x" for x in TICKS])
        ax.grid(alpha=.25)
        ax.set_title(f"{b} (growth of 1, 2011-11-25 to 2019-01-02, 20.8 bps, log scale)", fontsize=10)
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.legend(h, l, loc="lower center", ncol=4, fontsize=8, frameon=False)
    fig.savefig(X / fname, dpi=110)
    plt.close(fig)


rules = [k for k in order if LABEL[k][1] == "rule"]
panel(rules + ["hold_proxy"], "combined_chart_rules.png", "The six switch rules against holding the proxy (2011-11-25 to 2019-01-02, after 20.8 bps; dashed = reference)", w_hi=("threeindex_timed", "index_rule_timed", "sc100_timed"))
panel(order, "combined_chart_all.png", "Every variation tested on 2011-11-25 to 2019-01-02 (after 20.8 bps; solid = switch rules, dashed = references)")
panel(["hold_proxy", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed", "nifty100_alone", "midcap100_alone", "smallcap100_alone", "threeindex_timed"], "combined_chart_references.png",
      "The references: holding the proxy, constant mixes, the sleeve alone and each index alone (three-index timed rule for scale)")
print("\nwritten:", *sorted(p.name for p in X.glob("combined_*")))
