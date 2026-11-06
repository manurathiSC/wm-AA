# -*- coding: utf-8 -*-
"""
Deep dive, analyst "years": print the key tables as Markdown to stdout, formatted
from the CSVs in evidence/why_n100sc100/deep/ (no numbers are computed here
beyond rounding and string formatting).
"""

from __future__ import annotations

import pandas as pd

from why_n100sc100 import OUT

DEEP = OUT / "deep"


def pct(x, d=1):
    return "" if pd.isna(x) else f"{x * 100:+.{d}f}%"


def pp(x, d=1):
    return "" if pd.isna(x) else f"{x * 100:+.{d}f}"


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def year_table(w: pd.DataFrame, leg: str, sleeve: str) -> str:
    g = w[(w["leg"] == leg) & (w["sleeve"] == sleeve) & (w["sample"] != "mixed")]
    rows = []
    for _, r in g.iterrows():
        reg = r["SC100_label"] + (" V" if r["SC100_V"] else "")
        rows.append({"Year": r["period"] + ("*" if r["partial"] else ""), "Sample": r["sample"],
                     "SC100 regime": reg, "bh": pct(r["bh_ret"]), "pair": pct(r["pair_ret"]),
                     "sc100": pct(r["sc100_ret"]), "triple": pct(r["triple_ret"]),
                     "pair−bh (pp)": pp(r["pair_minus_bh"]), "pair−sc100 (pp)": pp(r["pair_minus_sc100"]),
                     "bh worst fall d/F": f"{r['bh_dd_daily'] * 100:.0f}/{r['bh_dd_friday'] * 100:.0f}%",
                     "pair worst fall d/F": f"{r['pair_dd_daily'] * 100:.0f}/{r['pair_dd_friday'] * 100:.0f}%",
                     "pair in equity": f"{r['pair_in_equity'] * 100:.0f}%",
                     "pair switches": int(r["pair_switches"])})
    return md(pd.DataFrame(rows))


def main() -> None:
    w = pd.read_csv(DEEP / "years_index_diffs.csv")
    print("### SC100, cash sleeve\n")
    print(year_table(w, "SC100", "cash"))
    print("\n### Blend (N100/MC100/SC100 equal weight), cash sleeve\n")
    print(year_table(w, "blend", "cash"))

    # portfolios
    v = pd.read_csv(DEEP / "years_portfolio_pair_vs.csv")
    vc = v[v["sleeve"] == "cash"].set_index(["sample", "period"])
    rows = []
    for _, r in v[v["sleeve"] == "50/50"].iterrows():
        c = vc.loc[(r["sample"], r["period"])]
        rows.append({"Year": r["period"], "Sample": r["sample"] + (" (parents)" if r["sample"] == "OOS" else " (AA books)"),
                     "SC100 same dates": f"{pct(r['SC100_ret_same_dates'])} {r['SC100_label']}{' V' if r['SC100_V'] else ''}",
                     "parent": pct(r["avg_parent_ret"]), "pair 50/50": pct(r["avg_pair_ret"]),
                     "pair cash": pct(c["avg_pair_ret"]), "sc100 50/50": pct(r["avg_sc100_ret"]),
                     "current 50/50": pct(r["avg_current_ret"]), "triple 50/50": pct(r["avg_triple_ret"]),
                     "pair−parent (pp)": pp(r["avg_pair_minus_parent"]),
                     "books pair>parent / >sc100 / >current": f"{r['books_pair_beats_parent']}/{r['books_pair_beats_sc100']}/{r['books_pair_beats_current']}",
                     "worst fall pair / parent": f"{r['avg_pair_dd_daily'] * 100:.0f}/{r['avg_parent_dd_daily'] * 100:.0f}%"})
    print("\n### Portfolios, average of the 4 books, by calendar year (p = partial)\n")
    print(md(pd.DataFrame(rows)))

    s = pd.read_csv(DEEP / "years_portfolio_summary.csv")
    rows = []
    for _, r in s.iterrows():
        rows.append({"Sample": r["sample"], "Sleeve": r["sleeve"], "Slices": r["slices"],
                     "pair vs parent W/T/L (avg)": f"{r['slices_pair_beats_parent_avg']}/{r['slices_tie_parent_avg']}/{r['slices_pair_behind_parent_avg']}",
                     "book-years pair>parent": f"{r['book_years_pair_beats_parent']}/{r['book_years']}",
                     "pair vs sc100 W/T/L": f"{r['slices_pair_beats_sc100_avg']}/{r['slices_tie_sc100_avg']}/{r['slices_pair_behind_sc100_avg']}",
                     "pair vs current W/T/L": f"{r['slices_pair_beats_current_avg']}/{r['slices_tie_current_avg']}/{r['slices_pair_behind_current_avg']}",
                     "pair vs triple W/T/L": f"{r['slices_pair_beats_triple_avg']}/{r['slices_tie_triple_avg']}/{r['slices_pair_behind_triple_avg']}",
                     "compounded pair / parent": f"{r['pair_compound_avg_pct']:+.0f}% / {r['parent_compound_avg_pct']:+.0f}%"})
    print("\n### Portfolio year counts\n")
    print(md(pd.DataFrame(rows)))

    # win counts, indices
    wn = pd.read_csv(DEEP / "years_summary_wins.csv")
    wn = wn[(wn["scope"] == "all slices") & (wn["leg"].isin(["N50", "N100", "MC100", "SC100", "blend", "MC150", "SC250", "Micro250"]))]
    rows = []
    for _, r in wn.sort_values(["sample", "sleeve", "leg"], ascending=[False, True, True]).iterrows():
        rows.append({"Sample": r["sample"], "Sleeve": r["sleeve"], "Leg": r["leg"], "Slices": r["n"],
                     "pair vs bh W/T/L": f"{r['vs_bh_wins']}/{r['vs_bh_ties']}/{r['vs_bh_losses']}",
                     "sign p": f"{r['vs_bh_sign_p']:.2f}",
                     "mean gap (pp)": f"{r['vs_bh_mean_pp']:+.1f}", "mean log gap (pp)": f"{r['vs_bh_mean_log_gap_pp']:+.1f}",
                     "wealth ×bh": f"{r['vs_bh_wealth_ratio']:.2f}",
                     "pair vs sc100 W/T/L": f"{r['vs_sc100_wins']}/{r['vs_sc100_ties']}/{r['vs_sc100_losses']}",
                     "wealth ×sc100": f"{r['vs_sc100_wealth_ratio']:.2f}",
                     "triple vs pair W/T/L": f"{r['triple_vs_pair_wins']}/{r['triple_vs_pair_ties']}/{r['triple_vs_pair_losses']}",
                     "yrs pair fall shallower (d)": f"{r['dd_shallower_than_bh_daily']}/{r['n']}",
                     "worst yr pair / bh": f"{r['worst_year_pair_pct']:+.0f}% / {r['worst_year_bh_pct']:+.0f}%"})
    print("\n### Year counts on the indices (ties = |gap| ≤ 0.1 pp)\n")
    print(md(pd.DataFrame(rows)))

    # regime
    rg = pd.read_csv(DEEP / "years_summary_regime.csv")
    rg = rg[(rg["scope"] == "all slices") & (rg["regime_source"] == "SC100") & (rg["sleeve"] == "cash")
            & (rg["leg"].isin(["N50", "N100", "MC100", "SC100", "blend"]))]
    rows = []
    for (smp, reg), g in rg.groupby(["sample", "regime"], sort=False):
        d = {"Sample": smp, "SC100 regime (hindsight)": reg, "n": int(g["n"].iloc[0]), "slices": g["periods"].iloc[0]}
        for _, r in g.iterrows():
            d[r["leg"]] = f"{r['mean_pair_minus_bh_pp']:+.1f} ({r['pair_beats_bh']}W/{r['pair_loses']}L)"
        rows.append(d)
    print("\n### Mean pair − bh (pp) by SC100 regime, cash sleeve\n")
    print(md(pd.DataFrame(rows)))

    # buckets
    bk = pd.read_csv(DEEP / "years_patterns_buckets.csv")
    bk = bk[(bk["sleeve"] == "cash") & (bk["leg"].isin(["SC100", "blend", "N100"]))]
    rows = []
    for (dim, b, smp), g in bk.groupby(["dimension", "bucket", "sample"]):
        d = {"Split": dim, "Bucket": b, "Sample": smp, "n": int(g["n"].iloc[0]), "slices": g["periods"].iloc[0]}
        for _, r in g.iterrows():
            d[r["leg"]] = f"{r['mean_pair_minus_bh_pp']:+.1f} ({r['pair_beats_bh']}W/{r['pair_loses']}L)"
        rows.append(d)
    print("\n### Mean pair − bh (pp) by bucket, cash sleeve\n")
    print(md(pd.DataFrame(rows).sort_values(["Sample", "Split", "Bucket"], ascending=[False, True, True])))

    be = pd.read_csv(DEEP / "years_patterns_breakeven.csv")
    be = be[(be["x"] == "SC100_ret")]
    rows = [{"Leg": r["leg"], "Sleeve": r["sleeve"], "Sample": r["sample"], "n": r["n"],
             "gap = a + b × SC100 year": f"{r['intercept_pp']:+.1f} pp {r['slope']:+.2f}×", "R²": f"{r['r2']:.2f}",
             "break-even SC100 year": f"{r['breakeven_x_pct']:+.1f}%"} for _, r in be.iterrows()
            if r["leg"] in ("SC100", "blend", "N100", "N50", "MC100")]
    print("\n### Break-even: the SC100 year return at which pair − bh = 0\n")
    print(md(pd.DataFrame(rows)))

    q = pd.read_csv(DEEP / "years_spells_quality.csv")
    q = q[q["exit_year"].isna()]
    rows = [{"Rule": r["rule"], "Leg": r["leg"], "Sample": r["sample"], "Out-spells": r["spells"],
             "saved / whipsaw": f"{r['saved']}/{r['whipsaw']}",
             "median leg while out": f"{r['median_leg_ret_while_out_pct']:+.1f}%",
             "log gain saved / whipsaw / all": f"{r['sum_log_gain_saved']:+.2f} / {r['sum_log_gain_whipsaw']:+.2f} / {r['sum_log_gain_all']:+.2f}",
             "top-3 log gain": f"{r['top3_log_gain']:+.2f}", "top-3 spells": r["top3_spells"]} for _, r in q.iterrows()]
    print("\n### Out-spell quality (cash sleeve; ex post)\n")
    print(md(pd.DataFrame(rows)))

    bw = pd.read_csv(DEEP / "years_best_worst.csv")
    rows = [{"Leg": r["leg"], "Sample": r["sample"], "Kind": f"{r['kind']} {r['rank']}", "Year": r["period"],
             "bh": pct(r["bh_ret"]), "pair": pct(r["pair_ret"]), "gap (pp)": pp(r["pair_minus_bh"]),
             "in equity": f"{r['pair_in_equity'] * 100:.0f}%", "leg while out": pct(r["leg_ret_while_out"]),
             "path": r["path"]} for _, r in bw.iterrows()]
    print("\n### Best and worst years, pair vs bh, cash sleeve\n")
    print(md(pd.DataFrame(rows)))


if __name__ == "__main__":
    main()
