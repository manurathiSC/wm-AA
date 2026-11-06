# -*- coding: utf-8 -*-
"""Print the key sleeve tables as markdown, straight from the deep/sleeve_*.csv outputs."""

from __future__ import annotations

import pandas as pd

from deep_sleeve_common import DEEP


def pct(x, d=1):
    return "" if pd.isna(x) else f"{x * 100:+.{d}f}"


def pp(x, d=1):
    return "" if pd.isna(x) else f"{x:+.{d}f}"


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def main() -> None:
    y = pd.read_csv(DEEP / "sleeve_yearly_table.csv")
    for leg in ("SC100", "blend", "4-book avg"):
        x = y[y["leg"] == leg]
        t = pd.DataFrame({
            "Segment": x["segment"], "Sample": x["sample"],
            "In sleeve %": (x["pair_time_in_sleeve"] * 100).round(0).astype(int),
            "Gold": x["gold_ret"].map(pct), "Cash": x["cash_ret"].map(pct),
            "B&H": x["bh_ret"].map(pct),
            "Pair cash": x["pair_cash_ret"].map(pct), "Pair 50/50": x["pair_5050_ret"].map(pct),
            "Pair gold": x["pair_gold_ret"].map(pct),
            "50/50 − cash": x["lift_5050_minus_cash"].map(pct),
            "gold − 50/50": x["lift_gold_minus_5050"].map(pct),
            "Timing (pair cash − B&H)": x["timing_paircash_minus_bh"].map(pct),
            "Worst fall daily: B&H / cash / 50/50 / gold": [
                f"{r.bh_dd_daily*100:.0f} / {r.pair_cash_dd_daily*100:.0f} / {r.pair_5050_dd_daily*100:.0f} / {r.pair_gold_dd_daily*100:.0f}"
                for r in x.itertuples()],
            "Worst fall Friday: B&H / cash / 50/50 / gold": [
                f"{r.bh_dd_fri*100:.0f} / {r.pair_cash_dd_fri*100:.0f} / {r.pair_5050_dd_fri*100:.0f} / {r.pair_gold_dd_fri*100:.0f}"
                for r in x.itertuples()]})
        print(f"\n### Per-year, pair on {leg} (returns %, pp)\n")
        print(md(t))

    s = pd.read_csv(DEEP / "sleeve_spells.csv")
    t = pd.DataFrame({
        "#": s["spell"], "Sample": s["sample"],
        "Exit review → re-entry review": s["exit_review"] + " → " + s["reentry_review"],
        "Sleeve sessions (first → last)": s["first_sleeve_session"] + " → " + s["last_sleeve_session"],
        "Sessions": s["sessions"], "Weeks": s["weeks"],
        "SC100": s["SC100_ret"].map(pct), "Blend": s["blend_ret"].map(pct),
        "Gold": s["gold_ret"].map(pct), "Cash": s["cash_ret"].map(pct),
        "Gold − cash": s["gold_minus_cash"].map(pct),
        "Gold beat cash": s["gold_beat_cash"].map({True: "yes", False: "no"})})
    print("\n### Defensive spells of the pair, 2014-07 → 2026-08 (returns %)\n")
    print(md(t))
    ss = pd.read_csv(DEEP / "sleeve_spells_summary.csv")
    t = pd.DataFrame({
        "Sample": ss["sample"], "Spells": ss["spells"], "Weeks": ss["weeks"],
        "Gold beat cash": ss["gold_beat_cash_hits"].astype(str) + " / " + ss["spells"].astype(str),
        "Mean gold − cash": ss["mean_gold_minus_cash"].map(pct),
        "Median gold − cash": ss["median_gold_minus_cash"].map(pct),
        "Gold compounded over spells": ss["compounded_gold_all_spells"].map(pct),
        "Cash compounded": ss["compounded_cash_all_spells"].map(pct),
        "SC100 compounded": ss["compounded_SC100_all_spells"].map(pct),
        "Blend compounded": ss["compounded_blend_all_spells"].map(pct),
        "Top spell share of sleeve lift": (ss["top_spell_share_of_lift"] * 100).round(0).astype(int).astype(str) + "%"})
    print("\n### Spell summary\n")
    print(md(t))

    d = pd.read_csv(DEEP / "sleeve_excess_decomposition.csv")
    d = d[d["leg"].isin(["SC100", "blend", "4-book avg", "N50", "N100", "MC100"])]
    t = pd.DataFrame({
        "Period": d["period"], "Leg": d["leg"],
        "B&H": d["bh_cagr"].map(pct), "Pair cash": d["pair_cash_cagr"].map(pct),
        "Pair 50/50": d["pair_5050_cagr"].map(pct), "Pair gold": d["pair_gold_cagr"].map(pct),
        "Timing pp": d["timing_pp"].map(pp), "Sleeve pp": d["sleeve_pp"].map(pp),
        "Total 50/50 − B&H pp": d["total_5050_vs_bh_pp"].map(pp),
        "Worst fall daily B&H / cash / 50/50 / gold": [
            f"{r.bh_dd_daily*100:.0f} / {r.pair_cash_dd_daily*100:.0f} / {r.pair_5050_dd_daily*100:.0f} / {r.pair_gold_dd_daily*100:.0f}"
            for r in d.itertuples()],
        "Worst fall Friday B&H / cash / 50/50 / gold": [
            f"{r.bh_dd_fri*100:.0f} / {r.pair_cash_dd_fri*100:.0f} / {r.pair_5050_dd_fri*100:.0f} / {r.pair_gold_dd_fri*100:.0f}"
            for r in d.itertuples()]})
    print("\n### Excess over buy-and-hold: equity timing vs sleeve (CAGR %, pp/yr)\n")
    print(md(t))

    dr = pd.read_csv(DEEP / "sleeve_drift_vs_remix.csv")
    t = pd.DataFrame({"Period": dr["period"], "Leg": dr["leg"],
                      "Daily re-mix CAGR": dr["remix_cagr"].map(lambda v: pct(v, 2)),
                      "Drifting CAGR": dr["drift_cagr"].map(lambda v: pct(v, 2)),
                      "Drift − re-mix pp": dr["drift_minus_remix_pp"].map(lambda v: pp(v, 2)),
                      "Worst fall daily re-mix / drift": [f"{r.remix_dd_daily*100:.1f} / {r.drift_dd_daily*100:.1f}" for r in dr.itertuples()],
                      "Worst fall Friday re-mix / drift": [f"{r.remix_dd_fri*100:.1f} / {r.drift_dd_fri*100:.1f}" for r in dr.itertuples()]})
    print("\n### 50/50 sleeve: daily re-mix vs drifting\n")
    print(md(t))

    cf = pd.read_csv(DEEP / "sleeve_gold_counterfactual.csv")
    piv = cf.pivot_table(index="scenario", columns=["period", "leg"], values="pair_cagr", sort=False)
    t = piv.applymap(lambda v: pct(v, 1)).reset_index()
    t.columns = ["Scenario (while defensive)"] + [f"{p} {l}" for p, l in piv.columns]
    bh = cf.drop_duplicates(["period", "leg"]).set_index(["period", "leg"])["bh_cagr"]
    t.loc[len(t)] = ["buy & hold (reference)"] + [pct(bh[(p, l)], 1) for p, l in piv.columns]
    print("\n### Gold-rally counterfactuals: pair CAGR % under alternative sleeves\n")
    print(md(t))

    pl = pd.read_csv(DEEP / "sleeve_gold_timing_placebo.csv")
    t = pd.DataFrame({"Period": pl["period"], "Share defensive": pl["share_defensive"].map(lambda v: f"{v:.0%}"),
                      "Actual lift (log %/yr)": pl["actual_lift_log_per_yr"].map(lambda v: f"{v*100:.2f}"),
                      "Placebo median": pl["placebo_median_lift_log_per_yr"].map(lambda v: f"{v*100:.2f}"),
                      "Placebo 5-95%": [f"{a*100:.2f} to {b*100:.2f}" for a, b in zip(pl["placebo_p05"], pl["placebo_p95"])],
                      "Actual percentile": pl["actual_percentile_in_placebo"].map(lambda v: f"{v:.0%}"),
                      "Unconditional part": pl["unconditional_expected_lift_log_per_yr"].map(lambda v: f"{v*100:.2f}"),
                      "Timing part": pl["timing_part_log_per_yr"].map(lambda v: f"{v*100:+.2f}")})
    print("\n### Gold-timing placebo (sleeve lift of 50/50 over cash)\n")
    print(md(t))

    dc = pd.read_csv(DEEP / "sleeve_sc100_declines.csv")
    dc = dc[dc["method"] == "zigzag 10%"]
    t = pd.DataFrame({"Peak → trough (Fri)": dc["peak_fri"] + " → " + dc["trough_fri"], "Weeks": dc["weeks"],
                      "Sample": dc["sample"], "SC100": dc["SC100_ret"].map(pct), "Gold": dc["gold_ret"].map(pct),
                      "Cash": dc["cash_ret"].map(pct), "Pair defensive % of sessions": (dc["pair_share_sessions_defensive"] * 100).round(0).astype(int),
                      "Pair cash": dc["pair_SC100_cash_ret"].map(pct), "Pair 50/50": dc["pair_SC100_5050_ret"].map(pct),
                      "Sleeve lift": dc["sleeve_lift_5050_minus_cash"].map(pct)})
    print("\n### SC100 declines of 10%+ (10% zig-zag on Friday closes), 2014-07 → 2026-08\n")
    print(md(t))

    co = pd.read_csv(DEEP / "sleeve_gold_sc100_corr.csv")
    co = co[~co["state"].str.startswith("Fisher")]
    t = pd.DataFrame({"Sample": co["sample"], "Pair state in week": co["state"], "Weeks": co["weeks"],
                      "Corr(gold, SC100)": co["corr_gold_SC100"].map(lambda v: f"{v:+.3f}"),
                      "Mean SC100 wk %": co["mean_SC100_wk"].map(lambda v: f"{v*100:+.2f}"),
                      "Mean gold wk %": co["mean_gold_wk"].map(lambda v: f"{v*100:+.2f}"),
                      "Gold up %": co["share_gold_up"].map(lambda v: f"{v:.0%}")})
    print("\n### Weekly gold vs SC100 correlation by the pair's state\n")
    print(md(t))


if __name__ == "__main__":
    main()
