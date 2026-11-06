"""Checks and charts for the AA data review (AGENT.md task 0).

Generic: nothing here knows about AA. `data_review.py` defines the inputs and calls these.
Imports nothing from AA/analysis.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


# ── fingerprints ──────────────────────────────────────────────────────────
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: Path) -> dict:
    st = path.stat()
    return {"path": str(path), "bytes": st.st_size, "sha256": sha256(path),
            "modified": pd.Timestamp(st.st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")}


# ── calendar ──────────────────────────────────────────────────────────────
def calendar_check(dates: pd.DatetimeIndex, ref: pd.DatetimeIndex, max_gap_sessions: int = 3) -> tuple[dict, pd.DataFrame]:
    """Compare a series' dates with a reference trading calendar over the series' own span.

    Returns a summary and a row per difference: kind in {missing, extra, duplicate, gap}.
    """
    raw = pd.DatetimeIndex(dates)
    dup = raw[raw.duplicated()]
    out_of_order = int((np.diff(raw.asi8) < 0).sum()) if len(raw) > 1 else 0
    d = raw.unique().sort_values()
    lo, hi = d.min(), d.max()
    span = ref[(ref >= lo) & (ref <= hi)]
    missing = span.difference(d)
    extra = d.difference(ref)
    rows = [{"date": x, "kind": "missing", "weekday": x.day_name()} for x in missing]
    rows += [{"date": x, "kind": "extra", "weekday": x.day_name()} for x in extra]
    rows += [{"date": x, "kind": "duplicate", "weekday": x.day_name()} for x in dup]
    # gaps measured in reference sessions between consecutive present dates (inside the span)
    present = d[d.isin(span)]
    pos = span.get_indexer(present)
    gaps = np.diff(pos) - 1 if len(pos) > 1 else np.array([], dtype=int)
    longest = int(gaps.max()) if len(gaps) else 0
    for i in np.where(gaps >= max_gap_sessions)[0]:
        rows.append({"date": present[i + 1], "kind": "gap", "weekday": present[i + 1].day_name(),
                     "sessions_missing_before": int(gaps[i]), "previous_date": present[i]})
    summary = {"first": lo.date(), "last": hi.date(), "rows": len(raw), "unique_dates": len(d),
               "ref_sessions_in_span": len(span), "missing": len(missing), "extra": len(extra),
               "weekend_rows": int((d.dayofweek >= 5).sum()), "duplicates": len(dup),
               "out_of_order": out_of_order, "longest_gap_sessions": longest}
    return summary, pd.DataFrame(rows)


# ── values ────────────────────────────────────────────────────────────────
def value_check(df: pd.DataFrame, price_cols: list[str], stale_n: int = 5) -> tuple[dict, pd.DataFrame]:
    """Blanks, non-positive values, OHLC consistency, stale runs and unit breaks for one series."""
    out = {}
    rows = []
    for c in price_cols:
        s = df[c]
        out[f"blank_{c}"] = int(s.isna().sum())
        out[f"nonpos_{c}"] = int((s <= 0).sum())
    if {"open", "high", "low", "close"}.issubset(df.columns):
        o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
        tol = 1e-9 * h.abs()
        bad = (l > o + tol) | (l > c + tol) | (h < o - tol) | (h < c - tol) | (l > h + tol)
        out["ohlc_violations"] = int(bad.sum())
        for d in df.index[bad.fillna(False)]:
            rows.append({"date": d, "kind": "ohlc", "detail": f"O {o[d]} H {h[d]} L {l[d]} C {c[d]}"})
    s = df[price_cols[-1]].dropna()
    # stale runs: identical consecutive values
    same = s.ne(s.shift()).cumsum()
    runs = s.groupby(same).agg(["size"]).assign(start=s.groupby(same).apply(lambda x: x.index[0]),
                                                 end=s.groupby(same).apply(lambda x: x.index[-1]),
                                                 value=s.groupby(same).first())
    long = runs[runs["size"] >= stale_n]
    out["stale_runs"] = int(len(long))
    out["longest_stale_run"] = int(runs["size"].max()) if len(runs) else 0
    for _, r in long.iterrows():
        rows.append({"date": r.start, "kind": "stale", "detail": f"{int(r['size'])} rows at {r.value} to {r.end.date()}"})
    # unit breaks: a day-on-day ratio beyond x5 either way
    ratio = (s / s.shift()).dropna()
    ub = ratio[(ratio > 5) | (ratio < 0.2)]
    out["unit_breaks"] = int(len(ub))
    for d, v in ub.items():
        rows.append({"date": d, "kind": "unit_break", "detail": f"ratio {v:.3f}"})
    return out, pd.DataFrame(rows)


def largest_moves(s: pd.Series, threshold: float, top: int = 10) -> pd.DataFrame:
    """Every daily move beyond the threshold, plus the `top` largest regardless of threshold."""
    r = s.dropna().pct_change().dropna()
    big = r[r.abs() >= threshold]
    topn = r.reindex(r.abs().sort_values(ascending=False).index[:top])
    allm = pd.concat([big, topn])
    allm = allm[~allm.index.duplicated()].sort_index()
    prev = s.dropna().shift().reindex(allm.index)
    return pd.DataFrame({"date": allm.index, "move": allm.values, "from": prev.values,
                         "to": s.reindex(allm.index).values,
                         "beyond_threshold": (allm.abs() >= threshold).values})


def returns_gap(a: pd.Series, b: pd.Series) -> dict:
    """Compare two level series on returns over their common dates."""
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    ra, rb = j.a.pct_change().dropna(), j.b.pct_change().dropna()
    yrs = (j.index[-1] - j.index[0]).days / 365.25
    ca = (j.a.iloc[-1] / j.a.iloc[0]) ** (1 / yrs) - 1
    cb = (j.b.iloc[-1] / j.b.iloc[0]) ** (1 / yrs) - 1
    diff = (ra - rb)
    worst = diff.abs().sort_values(ascending=False).head(5)
    return {"first": j.index[0].date(), "last": j.index[-1].date(), "common_dates": len(j),
            "cagr_a": ca, "cagr_b": cb, "gap_pp_per_year": 100 * (ca - cb),
            "corr_daily": float(ra.corr(rb)), "max_abs_daily_diff": float(diff.abs().max()),
            "worst_days": "; ".join(f"{d.date()} {100*diff[d]:+.2f}pp" for d in worst.index)}


# ── charts ────────────────────────────────────────────────────────────────
def _style(ax, title):
    import matplotlib
    ink = "#6b7280"
    ax.set_title(title, fontsize=9, color=ink, loc="left")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(ink)
    ax.tick_params(colors=ink, labelsize=7)
    ax.grid(True, color=ink, alpha=0.15, linewidth=0.5)
    ax.set_facecolor("none")


def series_panel(s: pd.Series, name: str, out: Path, threshold: float, log: bool = True) -> Path:
    """Level (log), daily returns over time, and histogram of daily returns, one PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = s.dropna()
    r = s.pct_change().dropna()
    fig, axes = plt.subplots(1, 3, figsize=(11, 2.6), gridspec_kw={"width_ratios": [2.2, 2.2, 1]})
    fig.patch.set_alpha(0)
    a0, a1, a2 = axes
    a0.plot(s.index, s.values, color="#2563eb", linewidth=1)
    if log and (s > 0).all():
        a0.set_yscale("log")
    _style(a0, f"{name}: level{' (log)' if log else ''}, {s.index[0].date()} → {s.index[-1].date()}")
    a1.plot(r.index, 100 * r.values, color="#0f766e", linewidth=0.6)
    a1.axhline(100 * threshold, color="#b45309", linewidth=0.6, linestyle="--")
    a1.axhline(-100 * threshold, color="#b45309", linewidth=0.6, linestyle="--")
    _style(a1, f"daily return, % (dashed: ±{100*threshold:g}% threshold)")
    a2.hist(100 * r.values, bins=80, color="#7c3aed", alpha=0.8)
    a2.set_yscale("log")
    _style(a2, "histogram of daily returns, %")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, transparent=True)
    plt.close(fig)
    return out


def overlay_chart(series: dict[str, pd.Series], title: str, out: Path, log: bool = True) -> Path:
    """Several level series rebased to 1 on their common first date."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    j = pd.concat(series, axis=1).dropna()
    j = j / j.iloc[0]
    fig, ax = plt.subplots(figsize=(11, 2.8))
    fig.patch.set_alpha(0)
    colors = ["#2563eb", "#dc2626", "#0f766e", "#b45309", "#7c3aed"]
    for i, c in enumerate(j.columns):
        ax.plot(j.index, j[c].values, linewidth=1, color=colors[i % len(colors)], label=c)
    if log:
        ax.set_yscale("log")
    _style(ax, f"{title}: growth of 1 from {j.index[0].date()} → {j.index[-1].date()}")
    ax.legend(fontsize=7, frameon=False, labelcolor="#6b7280")
    fig.tight_layout()
    fig.savefig(out, dpi=110, transparent=True)
    plt.close(fig)
    return out


def coverage_map(present: pd.DataFrame, title: str, out: Path) -> Path:
    """Date x name map: 1 = expected and present, 0 = expected and missing, NaN = not expected."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    fig, ax = plt.subplots(figsize=(11, max(2.0, 0.08 * present.shape[1] + 1)))
    fig.patch.set_alpha(0)
    cmap = ListedColormap(["#dc2626", "#93c5fd"])
    ax.imshow(present.T.values.astype(float), aspect="auto", cmap=cmap, interpolation="nearest", vmin=0, vmax=1)
    ax.set_yticks([])
    idx = present.index
    ticks = np.linspace(0, len(idx) - 1, 6).astype(int)
    ax.set_xticks(ticks)
    ax.set_xticklabels([idx[t].strftime("%Y-%m") for t in ticks])
    _style(ax, title)
    fig.tight_layout()
    fig.savefig(out, dpi=110, transparent=True)
    plt.close(fig)
    return out
