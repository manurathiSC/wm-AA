"""
T01, added after the run (2026-10-05). Descriptive, not pre-registered: the user asked for the rules
to be judged on drawdown and days in drawdown, not only on return.

For the reference rule and five comparison rules, the daily NAV path of every strategy realisation
and every circular-shift null draw is re-simulated (after cost, 20.8 bps; 50/50 GOLDBEES/LBES
sleeve), from evidence/headline/spliced_inputs.csv and decisions_all_configs.csv. A validity gate
requires every re-simulated path to reproduce the engine's nav_end and max_dd in realisations.csv
(relative 1e-9): this script then measures exactly the engine's books, with its own code.

Drawdown measures, on daily NAV (DD_t = NAV_t / running peak - 1):
  max_dd            deepest DD_t
  underwater_share  share of sessions with DD_t < 0
  below10_share     share of sessions with DD_t <= -10%
  longest_dd_days   longest peak-to-recovery stretch, calendar days (an unrecovered one runs to the
                    window end and is flagged)
  maxdd_recovery    calendar days from the deepest trough to the next new peak (NaN = not recovered)
  ulcer             sqrt(mean(DD_t^2)) x 100: average depth, weighting deep and long falls
  martin            CAGR / (ulcer / 100)
For the null, each measure's percentile = share of draws that are worse (deeper, longer, higher) +
0.5 x ties: high = the rule beats random timing at the same exposure.

    python AA/tests/T01/drawdown_profile.py    ->  evidence/diagnostics/drawdown_profile*.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence" / "headline"
OUT = HERE / "evidence" / "diagnostics"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"W1": ("2015-07-31", "2021-10-29"), "W2": ("2021-11-01", "2026-08-21")}
PAR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
CONFIGS = None        # every config in realisations.csv (all 30), set in main()
OW = 20.8 / 2 / 10_000
MEASURES = {"max_dd": True, "underwater_share": False, "below10_share": False, "longest_dd_days": False,
            "ulcer": False, "martin": True}            # True = higher is better


def simulate(px: np.ndarray, dpos: np.ndarray, tgt: np.ndarray, i0: int, i1: int) -> np.ndarray:
    """Daily NAV i0..i1 (T01.md §3 steps 6-7): trade at the session after a decision when the
    target changes; trims first, then top-ups E, G, L; build at i0+1; liquidate at i1."""
    trades = {}
    for d, e in zip(dpos, tgt):
        if d + 1 <= i1:
            trades[d + 1] = e
    units, acct, held = np.zeros(3), 1.0, None
    nav = np.empty(i1 - i0 + 1)
    nav[0] = 1.0
    ev = sorted(t for t in trades if t > i0)
    seg_start = i0 + 1
    for t in ev + [i1 + 1]:
        # mark the sessions before this event with the current units
        if t > seg_start:
            nav[seg_start - i0:t - i0] = acct + px[seg_start:t] @ units
        if t > i1:
            break
        e = trades[t]
        if e != held:
            w = np.array([e, (1 - e) / 2, (1 - e) / 2])
            now = acct + units @ px[t]
            delta = w * now - units * px[t]
            for a in np.where(delta < 0)[0]:
                units[a] += delta[a] / px[t, a]; acct += -delta[a] * (1 - OW)
            for a in (0, 1, 2):
                if delta[a] > 0:
                    v = min(delta[a], acct); units[a] += v * (1 - OW) / px[t, a]; acct -= v
            held = e
        nav[t - i0] = acct + units @ px[t]
        seg_start = t + 1
    # liquidate at the last close
    nav[-1] = acct + (units * px[i1]).sum() * (1 - OW)
    return nav


def measures(nav: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    under = dd < -1e-12
    # longest drawdown: the longest gap between consecutive sessions at a high (a still-open one runs to the end)
    n = len(nav)
    at = np.where(~under)[0]
    dn = dates.values.astype("datetime64[D]").astype(np.int64)
    gaps = np.diff(dn[at]) if len(at) > 1 else np.array([0])
    longest = int(max(gaps.max(initial=0), dn[-1] - dn[at[-1]]))
    tr = int(np.argmin(dd))
    rec = np.where(nav[tr:] >= peak[tr] - 1e-12)[0]
    rec_days = (dates[tr + rec[0]] - dates[tr]).days if len(rec) and dd[tr] < 0 else np.nan
    yrs = (n - 1) / 252
    cagr = nav[-1] ** (1 / yrs) - 1
    ulcer = float(np.sqrt(np.mean(dd ** 2)) * 100)
    return {"cagr": cagr, "max_dd": float(dd.min()), "underwater_share": float(under.mean()),
            "below10_share": float((dd <= -0.10).mean()), "longest_dd_days": longest,
            "longest_unrecovered": bool(under[-1] and longest == int(dn[-1] - dn[at[-1]])),
            "maxdd_recovery_days": rec_days, "ulcer": ulcer, "martin": cagr / (ulcer / 100) if ulcer > 0 else np.nan}


def pctile(obs: float, draws: np.ndarray, higher_better: bool) -> float:
    worse = (draws < obs - 1e-12) if higher_better else (draws > obs + 1e-12)
    eq = np.abs(draws - obs) <= 1e-12
    return float((worse.sum() + 0.5 * eq.sum()) / len(draws) * 100)


def main():
    s = pd.read_csv(EV / "spliced_inputs.csv", parse_dates=["date"]).set_index("date")
    cal = s.index
    dec = pd.read_csv(EV / "decisions_all_configs.csv", parse_dates=["decision_date"])
    real = pd.read_csv(EV / "realisations.csv", keep_default_na=False, na_values=[""])
    real = real[real.cost_bps == 20.8]
    global CONFIGS
    CONFIGS = [c for c in dict.fromkeys(real.config) if c != "bh"]
    pos = {d: i for i, d in enumerate(cal)}
    rows, nrows, gate_n, gate_bad = [], [], 0, 0
    for book, par in PAR.items():
        px = np.c_[s[f"P_{par}"].to_numpy(), s["gold"].to_numpy(), s["cash"].to_numpy()]
        for w, (a, b) in WIN.items():
            i0 = pos[cal[cal <= pd.Timestamp(a)][-1]]; i1 = pos[pd.Timestamp(b)]
            dates = cal[i0:i1 + 1]
            bh = px[i0:i1 + 1, 0] / px[i0, 0]
            mb = measures(bh, dates)
            rows.append({"config": "hold", "book": book, "window": w, **mb})
            for c in CONFIGS:
                x = dec[(dec.config == c) & (dec.book == book) & (dec.window == w)].sort_values("decision_date")
                dpos = np.array([pos[d] for d in x.decision_date]); tgt = x.equity_target.to_numpy(dtype=float)
                rr = real[(real.config == c) & (real.book == book) & (real.window == w)]
                st = rr[rr.kind == "strategy"].iloc[0]
                nav = simulate(px, dpos, tgt, i0, i1)
                gate_n += 1
                gate_bad += int(abs(nav[-1] / st.nav_end - 1) > 1e-9 or abs(measures(nav, dates)["max_dd"] - st.max_dd) > 1e-9)
                m = measures(nav, dates)
                nl = rr[rr.kind == "null"].set_index("shift_k")
                draws = []
                for k, nr in nl.iterrows():
                    nv = simulate(px, dpos, np.roll(tgt, int(k)), i0, i1)
                    gate_n += 1
                    gate_bad += int(abs(nv[-1] / nr.nav_end - 1) > 1e-9)
                    mm = measures(nv, dates); mm["shift_k"] = int(k); draws.append(mm)
                D = pd.DataFrame(draws)
                pc = {f"pct_{k}": pctile(m[k], D[k].to_numpy(dtype=float), hb) for k, hb in MEASURES.items()}
                med = {f"null_med_{k}": float(D[k].median()) for k in MEASURES}
                rows.append({"config": c, "book": book, "window": w, **m, **pc, **med, "draws": len(D)})
                D.insert(0, "window", w); D.insert(0, "book", book); D.insert(0, "config", c)
                nrows.append(D)
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "drawdown_profile.csv", index=False)
    pd.concat(nrows).to_csv(OUT / "drawdown_profile_nulls.csv", index=False)
    print(f"GATE: re-simulated paths reproducing the engine's nav_end (and the strategy's max_dd): "
          f"{gate_n - gate_bad} of {gate_n} -> {'PASS' if gate_bad == 0 else 'FAIL'}")
    if gate_bad:
        raise SystemExit(1)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    f = R.copy()
    for k in ("max_dd", "underwater_share", "below10_share"):
        f[k] = (f[k] * 100).round(1)
    cols = ["config", "book", "window", "cagr", "max_dd", "underwater_share", "below10_share", "longest_dd_days",
            "maxdd_recovery_days", "ulcer", "martin", "pct_max_dd", "pct_underwater_share", "pct_longest_dd_days", "pct_ulcer"]
    f["cagr"] = (f["cagr"] * 100).round(2)
    for w in ("W1", "W2"):
        print(f"\n=== {w}: reference rule vs hold, per book")
        print(f[(f.window == w) & f.config.isin(["hold", "pct_w65_q25"])][cols].round(2).to_string(index=False))
    print("\n=== 4-book averages (descriptive); percentiles = median across books")
    agg = R.groupby(["window", "config"], sort=False).agg(
        cagr=("cagr", "mean"), max_dd=("max_dd", "mean"), underwater=("underwater_share", "mean"),
        below10=("below10_share", "mean"), longest=("longest_dd_days", "mean"), ulcer=("ulcer", "mean"), martin=("martin", "mean"),
        pct_uw=("pct_underwater_share", "median"), pct_longest=("pct_longest_dd_days", "median"), pct_ulcer=("pct_ulcer", "median"),
        pct_maxdd=("pct_max_dd", "median"))
    print(agg.round(3).to_string())
    agg.to_csv(OUT / "drawdown_profile_summary.csv")


if __name__ == "__main__":
    main()
