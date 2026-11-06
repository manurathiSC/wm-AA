"""
Check every number on the published T01 page (added 2026-10-05, after the user asked whether
the page's numbers are correct). Imports nothing from own_momentum.py, verify_own_momentum.py,
analyse.py or report.py.

1. End to end: re-runs the reference rule (pct_w65_q25, weekly, 50/50 GOLDBEES/LBES, 20.8 bps)
   from the RAW input files with its own code, per T01.md §3, and compares its CAGR, worst fall,
   sleeve share and switch count with the page's reference rows; B&H likewise.
2. Page vs evidence: every number in the page's embedded data block (from the saved published
   HTML) against evidence/headline/realisations.csv and daily_reference.csv.
3. Typed claims in the page's prose against analysis.log, verify_headline.json and audit.json.

    python AA/tests/T01/check_page.py <published_page.html>     # exit 0 = every check passed
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AA = ROOT / "AA"
EV = HERE / "evidence" / "headline"
PAIR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
WIN = {"W1": ("2015-07-31", "2021-10-29"), "W2": ("2021-11-01", "2026-08-21")}
OW = 20.8 / 2 / 10_000
fails, n_checks = [], 0


def check(name, ok, detail=""):
    global n_checks
    n_checks += 1
    if not ok:
        fails.append(f"{name}: {detail}")


# ── 1. independent re-run from raw files ───────────────────────────────────
def raw_panel():
    pub = pd.read_csv(AA / "Historical Data" / "parentIndices.csv")
    pub["date"] = pd.to_datetime(pub["date"], format="%d/%m/%y %H:%M")
    pub = pub.pivot(index="date", columns="scid", values="index").sort_index()
    nav = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "nav_curves_daily.csv", index_col=0, parse_dates=True)
    P = {}
    for book, par in PAIR.items():
        h = nav[f"before the books 2014-07 -> 2021-10|{book}|parent (no overlay)"].dropna()
        h = h[h.index <= "2021-10-29"]
        pp = pub[par].dropna()
        s = pd.concat([h, h.iloc[-1] * pp / pp.loc["2021-11-01"]])
        P[par] = s[~s.index.duplicated(keep="first")]
    cal = pd.DatetimeIndex(sorted(set().union(*[set(v.index) for v in P.values()])))
    P = pd.DataFrame({k: v.reindex(cal) for k, v in P.items()})
    g = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "gold_daily_ohlc_eikon.csv", parse_dates=["date"])
    lb = pd.read_csv(AA / "Historical Data" / "LBES_Adjusted_Price_data_2026_08_10.csv")
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    asof = lambda d, col: pd.merge_asof(pd.DataFrame({"date": cal}), d.sort_values("date")[["date", col]], on="date")[col].to_numpy()
    return P, pd.Series(asof(g, "close"), index=cal), pd.Series(asof(lb, "price"), index=cal)


def run_rule(p: pd.Series, gold: pd.Series, cash: pd.Series, t0: str, end: str):
    cal = p.index
    i0, i1 = cal.get_loc(cal[cal <= pd.Timestamp(t0)][-1]), cal.get_loc(pd.Timestamp(end))
    v = p.to_numpy()
    iso = [tuple(d.isocalendar())[:2] for d in cal]
    dec = [i0] + [i for i in range(i0 + 1, i1 + 1) if i == len(cal) - 1 or iso[i] != iso[i + 1]]
    def target(i):
        prev = v[i - 65:i]
        pct = (prev < v[i]).sum() / 65 * 100
        return 0.0 if pct < 25 else 1.0
    tgt = {i: target(i) for i in dec}
    px = np.c_[v, gold.to_numpy(), cash.to_numpy()]
    units, acct, held, nav, switches = np.zeros(3), 1.0, None, [], 0
    trade_at = {}
    for i in dec:
        if i + 1 <= i1:
            trade_at.setdefault(i + 1, tgt[i])          # next session's close
    for i in range(i0, i1 + 1):
        if i in trade_at and trade_at[i] != held:
            e = trade_at[i]
            w = np.array([e, (1 - e) / 2, (1 - e) / 2])
            now = acct + units @ px[i]
            delta = w * now - units * px[i]
            for a in np.where(delta < 0)[0]:
                units[a] -= -delta[a] / px[i, a]; acct += -delta[a] * (1 - OW)
            for a in (0, 1, 2):
                if delta[a] > 0:
                    b = min(delta[a], acct); units[a] += b * (1 - OW) / px[i, a]; acct -= b
            if held is not None:
                switches += 1
            held = e
        if i == i1:                                       # liquidate at the last close
            acct += (units * px[i]).sum() * (1 - OW); units[:] = 0
        nav.append(acct + units @ px[i])
    nav = np.array(nav)
    yrs = (i1 - i0) / 252
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    bh = v[i0:i1 + 1] / v[i0]
    sh = np.mean([tgt[i] < 1 for i in dec])
    return {"nav": nav, "bh_path": bh, "dates": cal[i0:i1 + 1],
            "cagr": nav[-1] ** (1 / yrs) - 1, "dd": dd, "share": sh, "switches": switches,
            "bh": bh[-1] ** (1 / yrs) - 1, "bh_dd": (bh / np.maximum.accumulate(bh) - 1).min(),
            "bh_cal": bh[-1] ** (252 / ((cal[i1] - cal[i0]).days / 365.25 * 252)) - 1}


def dd_measures(nav, dates):
    """Independent implementation: share of days >= 10% below the running peak, longest
    peak-to-new-peak stretch in calendar days (open at the end counts to the last date), Ulcer."""
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    last_peak_date, longest = dates[0], 0
    for t in range(len(nav)):
        if dd[t] >= -1e-12:
            longest = max(longest, (dates[t] - last_peak_date).days)
            last_peak_date = dates[t]
    longest = max(longest, (dates[-1] - last_peak_date).days)
    return {"below10": float((dd <= -0.10).mean()), "longest": longest, "ulcer": float(np.sqrt((dd ** 2).mean()) * 100)}


def main(page_path: str):
    html = Path(page_path).read_text(encoding="utf-8")
    D = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    ref = {(r["window"], r["book"]): r for r in D["ref"]}

    P, gold, cash = raw_panel()
    print("1. independent re-run of your rule from raw files vs the page (CAGR in %)")
    for (w, b), r in ref.items():
        x = run_rule(P[PAIR[b]], gold, cash, *WIN[w])
        for k, tol in (("cagr", 6e-5), ("bh", 6e-5), ("dd", 6e-5), ("bh_dd", 6e-5), ("share", 6e-4)):
            check(f"rerun {w} {b} {k}", abs(x[k] - r[k]) <= tol, f"rerun {x[k]:.5f} vs page {r[k]}")
        check(f"rerun {w} {b} switches", x["switches"] == r["switches"], f"{x['switches']} vs {r['switches']}")
        if "dd_ref" in D:
            q = next(z for z in D["dd_ref"] if z["window"] == w and z["book"] == b)
            mr, mh = dd_measures(x["nav"], x["dates"]), dd_measures(x["bh_path"], x["dates"])
            for k, pk, tol in (("below10", "below10", 6e-4), ("ulcer", "ulcer", 6e-3)):
                check(f"dd {w} {b} rule {k}", abs(mr[k] - q[pk]) <= tol, f"{mr[k]} vs page {q[pk]}")
                check(f"dd {w} {b} hold {k}", abs(mh[k] - q["h_" + pk]) <= tol, f"{mh[k]} vs page {q['h_' + pk]}")
            check(f"dd {w} {b} rule longest", mr["longest"] == q["longest"], f"{mr['longest']} vs page {q['longest']}")
            check(f"dd {w} {b} hold longest", mh["longest"] == q["h_longest"], f"{mh['longest']} vs page {q['h_longest']}")
        print(f"   {w} {b}: rule {x['cagr']*100:6.2f} (page {r['cagr']*100:6.2f}) | hold {x['bh']*100:6.2f} (page {r['bh']*100:6.2f}, "
              f"calendar-year basis {x['bh_cal']*100:6.2f}) | worst fall {x['dd']*100:6.2f} (page {r['dd']*100:6.2f}) | switches {x['switches']} ({r['switches']})")

    # ── 2. page data vs evidence ──
    real = pd.read_csv(EV / "realisations.csv", keep_default_na=False, na_values=[""])
    a = real[real.cost_bps == 20.8]
    bh = real[real.kind == "bh"].set_index(["book", "window"])
    for (w, b), r in ref.items():
        s = a[(a.kind == "strategy") & (a.config == "pct_w65_q25") & (a.book == b) & (a.window == w)].iloc[0]
        d = np.sort(a[(a.kind == "null") & (a.config == "pct_w65_q25") & (a.book == b) & (a.window == w)].cagr.to_numpy())
        check(f"page draws {w} {b}", len(d) == len(r["draws"]) and np.abs(np.round(d, 4) - np.array(r["draws"])).max() < 1e-9)
        pct = ((d < s.cagr).sum() + 0.5 * (d == s.cagr).sum()) / len(d) * 100
        for k, val in (("cagr", s.cagr), ("bh", bh.loc[(b, w), "cagr"]), ("dd", s.max_dd), ("bh_dd", bh.loc[(b, w), "max_dd"]),
                       ("null_med", np.median(d)), ("edge", s.cagr - np.median(d)), ("mde", 2.8 * np.std(d, ddof=1)),
                       ("calmar", s.calmar), ("bh_calmar", bh.loc[(b, w), "calmar"]), ("pct", pct)):
            tol = 0.051 if k == "pct" else 6e-4 if "calmar" in k else 6e-5
            check(f"page {w} {b} {k}", abs(val - r[k]) <= tol, f"evidence {val} vs page {r[k]}")
    # path chart endpoints
    dr = pd.read_csv(EV / "daily_reference.csv", parse_dates=["date"])
    for key, pth in D["paths"].items():
        w, b = key.split("|")
        s = a[(a.kind == "strategy") & (a.config == "pct_w65_q25") & (a.book == b) & (a.window == w)].iloc[0]
        check(f"path {key} end", abs(pth["nav"][-1] - s.nav_end) < 6e-6 and abs(pth["bh"][-1] - (1 + bh.loc[(b, w), "total_return"])) < 6e-6)
        check(f"path {key} length", len(pth["d"]) == len(dr[(dr.book == b) & (dr.window == w) & (dr.cost_bps == 20.8)]))
    # sweep table and KPIs
    S = a[a.kind == "strategy"]
    for row in D["sweep"]:
        c = row["config"]
        for w in ("W1", "W2"):
            pcts, edges, n90 = [], [], 0
            for b in PAIR:
                s = S[(S.config == c) & (S.book == b) & (S.window == w)].iloc[0]
                d = a[(a.kind == "null") & (a.config == c) & (a.book == b) & (a.window == w)].cagr.to_numpy()
                p_ = ((d < s.cagr).sum() + 0.5 * (d == s.cagr).sum()) / len(d) * 100
                rep = s.n_switches >= 4 and 0.05 <= s.share_sleeve_weeks <= 0.95
                pcts.append(p_); edges.append(s.cagr - np.median(d)); n90 += int(p_ >= 90 and rep)
            avg = S[(S.config == c) & (S.window == w)].cagr.mean()
            check(f"sweep {c} {w} med_pct", abs(np.median(pcts) - row[w]["med_pct"]) <= 0.051, f"{np.median(pcts)} vs {row[w]['med_pct']}")
            check(f"sweep {c} {w} med_edge", abs(np.median(edges) - row[w]["med_edge"]) <= 6e-5)
            check(f"sweep {c} {w} n90", n90 == row[w]["n90"], f"{n90} vs {row[w]['n90']}")
            check(f"sweep {c} {w} avg_cagr", abs(avg - row[w]["avg_cagr"]) <= 6e-5)
            if "ulcer" in row[w]:
                DPs = pd.read_csv(HERE / "evidence" / "diagnostics" / "drawdown_profile.csv")
                x = DPs[(DPs.window == w) & (DPs.config == c)]
                check(f"sweep {c} {w} dd n", len(x) == 4)
                check(f"sweep {c} {w} avg_dd", abs(S[(S.config == c) & (S.window == w)].max_dd.mean() - row[w]["avg_dd"]) <= 6e-5)
                check(f"sweep {c} {w} below10", abs(x.below10_share.mean() - row[w]["below10"]) <= 6e-4)
                check(f"sweep {c} {w} longest", round(x.longest_dd_days.mean()) == row[w]["longest"])
                check(f"sweep {c} {w} ulcer", abs(x.ulcer.mean() - row[w]["ulcer"]) <= 6e-3)
                check(f"sweep {c} {w} pct_ulcer", abs(x.pct_ulcer.median() - row[w]["pct_ulcer"]) <= 0.051)
    print(f"2. page data vs evidence: {len(D['sweep'])} sweep rows, {len(ref)} reference rows, {len(D['paths'])} paths checked")

    # drawdown table: 4-book averages vs drawdown_profile.csv
    if "dd" in D:
        DP = pd.read_csv(HERE / "evidence" / "diagnostics" / "drawdown_profile.csv")
        for z in D["dd"]:
            x = DP[(DP.window == z["window"]) & (DP.config == z["config"])]
            check(f"dd table {z['window']} {z['config']} n", len(x) == 4)
            for k, col, tol in (("cagr", "cagr", 6e-5), ("max_dd", "max_dd", 6e-5), ("below10", "below10_share", 6e-4), ("ulcer", "ulcer", 6e-3)):
                check(f"dd table {z['window']} {z['config']} {k}", abs(x[col].mean() - z[k]) <= tol, f"{x[col].mean()} vs {z[k]}")
            check(f"dd table {z['window']} {z['config']} longest", round(x.longest_dd_days.mean()) == z["longest"])
            if z["config"] != "hold":
                check(f"dd table {z['window']} {z['config']} pct_ulcer", abs(x.pct_ulcer.median() - z["pct_ulcer"]) <= 0.051)
        print(f"   drawdown table: {len(D['dd'])} rows checked against drawdown_profile.csv")

    if "hold_dd" in D:
        DPh = pd.read_csv(HERE / "evidence" / "diagnostics" / "drawdown_profile.csv")
        for w, hv in D["hold_dd"].items():
            x = DPh[(DPh.window == w) & (DPh.config == "hold")]
            bhr = bh.xs(w, level="window")
            check(f"hold row {w} cagr", abs(bhr.cagr.mean() - hv["cagr"]) <= 6e-5 and abs(x.cagr.mean() - hv["cagr"]) <= 6e-5)
            check(f"hold row {w} max_dd", abs(bhr.max_dd.mean() - hv["max_dd"]) <= 6e-5)
            check(f"hold row {w} ulcer/below10/longest", abs(x.ulcer.mean() - hv["ulcer"]) <= 6e-3 and abs(x.below10_share.mean() - hv["below10"]) <= 6e-4 and round(x.longest_dd_days.mean()) == hv["longest"])

    # ── 3. typed claims in the prose ──
    log = (HERE / "analysis.log").read_text(encoding="utf-8")
    vj = json.loads((HERE / "verify_headline.json").read_text(encoding="utf-8"))
    au = json.loads((EV / "audit.json").read_text(encoding="utf-8"))
    draws = sorted({len(r["draws"]) for r in D["ref"]})
    check("text: 237–312 draws", draws == [237, 312], str(draws))
    mde = [r["mde"] for r in D["ref"]]
    check("text: MDE 12–18 pp", 0.115 <= min(mde) and max(mde) <= 0.185, f"{min(mde):.4f}–{max(mde):.4f}")
    mult = [float(x) for x in re.findall(r"\| (?:W1|W2) \| 00\d\d \| \S+ \| [\d.]+% \| [\d.]+ \| yes \| [\d.]+% \| [\d.]+ \| ([\d.]+) \|", log)]
    check("text: best-row 35th–83rd", len(mult) == 8 and round(min(mult)) == 35 and round(max(mult)) == 83, str(mult))
    trip = {r["config"]: r for r in D["sweep"]}["triple"]
    check("text: triple 4 of 4 (2021–26), 0 of 4 (2015–21)", trip["W2"]["n90"] == 4 and trip["W1"]["n90"] == 0)
    tot = sum(v.get("compared", 0) for v in vj["checks"].values()) if isinstance(vj.get("checks"), dict) else None
    m = re.search(r"verify_headline\.json verdict PASS; total compared (\d+), failures (\d+)", log)
    check("text: 459,722 comparisons, 0 failures", m and int(m[1]) == 459722 and int(m[2]) == 0, str(m and m.groups()))
    pit = au["point_in_time"]
    check("text: 192,584 point-in-time checks, 0 violations", pit["checks"] == 192584 and pit["violations"] == 0, str(pit.get("checks")))
    ndec = sum(1 for _ in open(EV / "decisions_all_configs.csv")) - 1
    check("text: 78,088 decisions", ndec == 78088 and "192,584 point-in-time checks over 78,088 decisions" in html, str(ndec))
    v = D["verdict"]
    check("text: 2 of 4 / 0 of 4 (C1)", v["C1"] == {"W1": 2, "W2": 0})
    S_ = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "summary_stats.csv")
    gap = []
    for bk in PAIR:
        q = S_[(S_.period == "live 2021-11 -> 2026-08") & (S_.aa == bk)].set_index("strategy").cagr
        gap.append(q["published parent NAV"] - q["parent (no overlay)"])
    check("text: rebuild 0.5–3.3 pp/yr below published", round(min(gap) * 100, 1) == 0.5 and round(max(gap) * 100, 1) == 3.3, str(gap))

    print(f"\n{n_checks} checks, {len(fails)} failed")
    for f in fails:
        print("  FAIL", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1])
