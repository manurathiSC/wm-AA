"""Independent review of the T07 tag sources (D20-D23), written by the reviewer agent, 2026-11-12.

Run from AA/:   python -I data/review_tag_sources.py
Reads only: D20/D21/D22 and the D23 panels (read exception, Manu 2026-11-12), plus APPROVED D17 (calendar),
D19 (baskets) and D05 (skipped flags).  Read-only: nothing under Historical Data/ or data/holdings_matrix/ is
written.  Outputs go to data/review/2026-11-12_tag_sources/ (results.json, trace_table.csv, mismatches_*.csv)
and to a scratch folder (my own rebuilt panels, the corrupted copies for the self-test).

The rule (decided by Manu 2026-11-11) is implemented here from the reviewer spec, not from the puller's code.
Part A (checks 1-3) was written and run before the puller's modules were opened; part B (checks 4-9) uses them.
"""
import json
import hashlib
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

AA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(AA)
EXT = "Historical Data/extended_2026-11-12/"
OUT = "data/review/2026-11-12_tag_sources/"
SCRATCH = os.environ.get(
    "REVIEW_SCRATCH",
    r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\ea0af580-06c7-4ce3-8c4f-77d4828a38b0\scratchpad\review_tag",
)
os.makedirs(OUT, exist_ok=True)
os.makedirs(SCRATCH, exist_ok=True)
PARENTS = ["0003", "0007", "0010", "0029"]
SIGNAL_END = pd.Timestamp("2026-10-30")
BANDS = ["Large", "Mid", "Small and below"]
INDEX_BAND = {
    "NIFTY 100": "Large",
    "NIFTY MIDCAP 150": "Mid",
    "NIFTY SMALLCAP 250": "Small and below",
    "NIFTY MICROCAP 250": "Small and below",
}
BUCKET_OF_INDEX = {
    "NIFTY 100": "Large Cap",
    "NIFTY MIDCAP 150": "Mid Cap",
    "NIFTY SMALLCAP 250": "Small Cap",
    "NIFTY MICROCAP 250": "Micro Cap",
}
R = {}  # results


def rd(path, **kw):
    return pd.read_csv(path, keep_default_na=False, na_values=[""], low_memory=False, **kw)


def band_of_rank(rank):
    rank = np.asarray(rank)
    return np.where(rank <= 100, "Large", np.where(rank <= 250, "Mid", "Small and below"))


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def jdefault(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o.date())
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def load_raw():
    d20 = rd(EXT + "mcap_universe/mcap_universe_ordinary.csv")
    d21 = rd(EXT + "membership/index_constituents_monthly.csv")
    d22 = rd(EXT + "symbology/symbology_changes.csv")
    return d20, d21, d22


def load_calendar():
    """D17 sessions: union over the four parents' published NAV dates (calendar of sessions)."""
    sess = {}
    for p in PARENTS:
        n = rd(f"Historical Data/extended_2026-11-06/published_nav/SCMO_{p}.csv")
        sess[p] = pd.to_datetime(n["_id.date"], format="%Y/%m/%d").sort_values().reset_index(drop=True)
    return sess


# ----------------------------------------------------------------------------------------------
# my own rank / membership panel (check 3)
# ----------------------------------------------------------------------------------------------
def my_rank_panel(d20):
    r = d20[d20["mcap"].notna()].copy()
    r = r.sort_values(["date", "mcap", "quote_id"], ascending=[True, False, True], kind="mergesort")
    r["rank"] = r.groupby("date").cumcount() + 1
    r["n_ranked"] = r.groupby("date")["rank"].transform("max")
    r["band"] = band_of_rank(r["rank"])
    return r[["date", "quote_id", "isin", "ticker", "mcap", "rank", "n_ranked", "band"]].reset_index(drop=True)


def my_membership_panel(d21):
    m = d21[["snapshot_date", "index_name", "isin", "symbol"]].copy()
    m["band"] = m["index_name"].map(INDEX_BAND)
    return m.reset_index(drop=True)


def compare_frames(mine, theirs, key, fields, label):
    """Row-for-row comparison on `key`; null-aware; returns counts and the list of differing rows."""
    out = {"label": label, "rows_mine": len(mine), "rows_theirs": len(theirs)}
    out["dup_keys_mine"] = int(mine.duplicated(key).sum())
    out["dup_keys_theirs"] = int(theirs.duplicated(key).sum())
    m = mine.merge(theirs, on=key, how="outer", suffixes=("_m", "_t"), indicator=True)
    out["only_in_mine"] = int((m["_merge"] == "left_only").sum())
    out["only_in_theirs"] = int((m["_merge"] == "right_only").sum())
    both = m[m["_merge"] == "both"]
    out["rows_compared"] = int(len(both))
    diffs = {}
    bad = pd.Series(False, index=both.index)
    for f in fields:
        a, b = both[f + "_m"], both[f + "_t"]
        if pd.api.types.is_float_dtype(a) or pd.api.types.is_float_dtype(b):
            d = ~((a == b) | (a.isna() & b.isna()))
        else:
            d = ~((a == b) | (a.isna() & b.isna()))
        diffs[f] = int(d.sum())
        bad |= d
    out["field_diffs"] = diffs
    out["rows_with_any_diff"] = int(bad.sum())
    out["_bad_rows"] = both[bad]
    out["_only"] = m[m["_merge"] != "both"]
    out["zero_differences"] = bool(
        out["only_in_mine"] == 0 and out["only_in_theirs"] == 0 and out["rows_with_any_diff"] == 0
        and out["dup_keys_mine"] == 0 and out["dup_keys_theirs"] == 0
    )
    return out


def strip_private(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------------------------
# CHECK 1
# ----------------------------------------------------------------------------------------------
def check1(d20, d21, d22, sess):
    c = {}
    exp20 = ["date", "quote_id", "instrument_id", "ric", "ticker", "full_name", "isin", "close", "mcap",
             "mcap_scaled_in_cr", "updated_at", "instrument_type", "instrument_class"]
    exp21 = ["snapshot_date", "index_name", "symbol", "isin", "company_name", "market_cap_bucket", "inserted_at"]
    c["columns_d20_ok"] = list(d20.columns) == exp20
    c["columns_d21_ok"] = list(d21.columns) == exp21
    c["d22_columns"] = list(d22.columns)
    c["rows"] = {"d20": len(d20), "d21": len(d21), "d22": len(d22)}
    c["d20_dup_date_quote_id"] = int(d20.duplicated(["date", "quote_id"]).sum())
    nn = d20[d20["isin"].notna()]
    c["d20_dup_date_isin_nonnull"] = int(nn.duplicated(["date", "isin"]).sum())
    c["d20_dup_date_isin_incl_null_as_equal"] = int(d20.duplicated(["date", "isin"]).sum())
    c["d20_ordinary_only"] = bool((d20["instrument_class"] == "ordinary").all())
    c["d20_mcap_nonpositive"] = int((d20["mcap"] <= 0).sum())
    c["d20_close_nonpositive"] = int((d20["close"] <= 0).sum())
    c["d20_nulls"] = {k: int(v) for k, v in d20.isna().sum().items() if v}
    # mcap / mcap_scaled consistency
    ok = d20["mcap"].notna()
    ratio = (d20.loc[ok, "mcap"] / 1e7 / d20.loc[ok, "mcap_scaled_in_cr"])
    c["mcap_vs_scaled_cr_max_rel_dev"] = float((ratio - 1).abs().max())
    # ranks and where the null rows sit
    r = my_rank_panel(d20)
    ranked = r.copy()
    c["null_isin_rows_ranked"] = int(ranked["isin"].isna().sum())
    c["null_isin_best_rank"] = int(ranked.loc[ranked["isin"].isna(), "rank"].min())
    c["null_isin_in_top250"] = int((ranked["isin"].isna() & (ranked["rank"] <= 250)).sum())
    c["null_ticker_best_rank"] = int(ranked.loc[ranked["ticker"].isna(), "rank"].min())
    c["null_ticker_in_top250"] = int((ranked["ticker"].isna() & (ranked["rank"] <= 250)).sum())
    c["null_isin_by_year"] = d20[d20["isin"].isna()].groupby(d20["date"].str[:4]).size().to_dict()
    c["null_ticker_by_year"] = d20[d20["ticker"].isna()].groupby(d20["date"].str[:4]).size().to_dict()
    c["null_mcap_by_year"] = d20[d20["mcap"].isna()].groupby(d20["date"].str[:4]).size().to_dict()
    nm = d20[d20["mcap"].isna()]
    c["null_mcap_rows_detail"] = nm.groupby("date").size().to_dict() if len(nm) < 60 else "see null_mcap_by_year"
    c["null_mcap_rows_with_isin"] = int(nm["isin"].notna().sum())
    c["rank_of_null_isin_quantiles"] = ranked.loc[ranked["isin"].isna(), "rank"].quantile([0, .25, .5, .75, 1]).to_dict()
    # ties in mcap among ranked rows (tie-break by quote_id matters only here)
    tie = ranked.duplicated(["date", "mcap"], keep=False)
    c["mcap_ties_ranked_rows"] = int(tie.sum())
    c["mcap_ties_within_top_260"] = int((tie & (ranked["rank"] <= 260)).sum())
    c["mcap_ties_straddling_a_band_edge"] = int(
        ranked[tie].groupby(["date", "mcap"])["rank"].apply(
            lambda s: bool(((s.min() <= 100) & (s.max() > 100)) | ((s.min() <= 250) & (s.max() > 250)))).sum())
    # same isin on two quote_ids on one date? (non-null isin dups are zero) ; isin <-> quote_id over time
    g = nn.groupby("isin")["quote_id"].nunique()
    c["d20_isins_with_more_than_one_quote_id"] = int((g > 1).sum())
    c["d20_isins_with_more_than_one_quote_id_list"] = g[g > 1].index.tolist()
    g2 = d20.groupby("quote_id")["isin"].nunique()
    c["d20_quote_ids_with_more_than_one_isin"] = int((g2 > 1).sum())
    # dates
    dates = pd.Series(sorted(pd.to_datetime(d20["date"].unique())))
    c["n_dates"] = int(len(dates))
    c["dates_first_last"] = [str(dates.iloc[0].date()), str(dates.iloc[-1].date())]
    c["dates_per_year"] = dates.groupby(dates.dt.year).size().to_dict()
    gaps = dates.diff().dt.days
    d26 = dates.dt.year == 2026
    c["max_gap_days_2026"] = int(gaps[d26].max())
    c["gaps_over_4_days_2026"] = [str(x.date()) for x in dates[d26 & (gaps > 4)]]
    c["weekend_dates"] = [str(x.date()) for x in dates[dates.dt.dayofweek >= 5]]
    all_sess = sorted(set(pd.concat(list(sess.values()))))
    all_sess = pd.Series(all_sess)
    pre = dates[dates.dt.year < 2026]
    not_last = []
    for dt in pre:
        if dt < pd.Timestamp("2019-01-01"):
            continue
        in_month = all_sess[(all_sess.dt.year == dt.year) & (all_sess.dt.month == dt.month)]
        if len(in_month) == 0 or dt != in_month.max():
            not_last.append(str(dt.date()))
    c["pre2026_dates_not_last_d17_session_of_month_2019on"] = not_last
    c["pre2026_dates_2025"] = [str(x.date()) for x in pre[pre.dt.year == 2025]]
    c["pre2018_2018_dates_last_weekday_of_month"] = {
        str(dt.date()): bool(dt == pd.Series(pd.bdate_range(dt.replace(day=1), dt + pd.offsets.MonthEnd(0))).max())
        for dt in pre[pre.dt.year == 2018]}
    s26 = all_sess[(all_sess >= pd.Timestamp("2026-01-01")) & (all_sess <= pd.Timestamp("2026-11-06"))]
    d26s = set(dates[d26])
    c["d17_sessions_2026_not_in_d20"] = [str(x.date()) for x in s26 if x not in d26s]
    c["d20_2026_dates_not_a_d17_session_to_2026-11-06"] = [str(x.date()) for x in dates[d26] if x not in set(s26) and x <= pd.Timestamp("2026-11-06")]
    c["d20_dates_after_2026-11-06"] = [str(x.date()) for x in dates[dates > pd.Timestamp("2026-11-06")]]
    # rows per date
    cnt = d20.groupby("date").size()
    c["rows_per_date_min_max"] = [int(cnt.min()), int(cnt.max())]
    nr = ranked.groupby("date").size()
    c["ranked_per_date_min_max_first_last"] = [int(nr.min()), int(nr.max()), int(nr.iloc[0]), int(nr.iloc[-1])]

    # D21
    c["d21_dup_snapshot_isin"] = int(d21.duplicated(["snapshot_date", "isin"]).sum())
    sizes = d21.groupby(["snapshot_date", "index_name"]).size().unstack()
    c["d21_index_sizes"] = {k: v for k, v in sizes.to_dict("index").items()}
    off = []
    for sd, row in sizes.iterrows():
        for ix, exp in zip(["NIFTY 100", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY MICROCAP 250"], [100, 150, 250, 250]):
            if row[ix] != exp:
                off.append((sd, ix, int(row[ix])))
    c["d21_snapshots_off_size"] = off
    # the extra microcap stock
    extra = []
    for sd, ix, n in off:
        sub = d21[(d21["snapshot_date"] == sd) & (d21["index_name"] == ix)]
        prev_dates = sorted(d21["snapshot_date"].unique())
        prev = prev_dates[prev_dates.index(sd) - 1] if prev_dates.index(sd) > 0 else None
        prev_isins = set(d21[(d21["snapshot_date"] == prev) & (d21["index_name"] == ix)]["isin"]) if prev else set()
        nxt = sub[~sub["isin"].isin(prev_isins)]
        for _, rr in nxt.iterrows():
            last_d20 = d20[d20["date"] == d20["date"].max()]
            m = d20[(d20["isin"] == rr["isin"])]
            extra.append({"snapshot": sd, "index": ix, "isin": rr["isin"], "symbol": rr["symbol"], "name": rr["company_name"],
                          "new_vs_prev_snapshot": True, "in_D20_any_date": bool(len(m)),
                          "in_D20_on_2026-11-02_or_nearest_before": bool(
                              len(d20[(d20["isin"] == rr["isin"]) & (d20["date"] == d20[d20["date"] <= sd]["date"].max())])),
                          "D20_dates_present": int(len(m)),
                          "D20_first_last": [m["date"].min(), m["date"].max()] if len(m) else None})
    c["d21_oversize_index_new_names"] = extra
    two = d21.groupby(["snapshot_date", "isin"])["index_name"].nunique()
    c["d21_isin_in_two_indices"] = int((two > 1).sum())
    c["d21_bucket_disagrees_with_index"] = int((d21["market_cap_bucket"] != d21["index_name"].map(BUCKET_OF_INDEX)).sum())
    c["d21_index_to_bucket"] = d21.groupby(["index_name", "market_cap_bucket"]).size().reset_index().values.tolist()
    c["d21_snapshot_dates"] = sorted(d21["snapshot_date"].unique())
    # D21 members present in D20 by ISIN (on latest D20 snapshot <= snapshot)  -> also check 7
    # D22
    q20 = set(d20["quote_id"])
    q22 = set(d22["quote_id"])
    c["d20_quote_ids"] = len(q20)
    c["d20_quote_ids_missing_from_d22"] = len(q20 - q22)
    c["d20_quote_ids_missing_from_d22_list"] = sorted(q20 - q22)[:20]
    c["d22_unique_quote_ids"] = len(q22)
    c["d22_dup_id"] = int(d22["id"].duplicated().sum())
    # ISIN -> quote_ids across D22 (isin and new_isin) and D20
    pairs = pd.concat([
        d22[["quote_id", "isin"]].dropna(),
        d22[["quote_id", "new_isin"]].rename(columns={"new_isin": "isin"}).dropna(),
        d20[["quote_id", "isin"]].dropna().drop_duplicates(),
    ]).drop_duplicates()
    gi = pairs.groupby("isin")["quote_id"].nunique()
    c["isins_mapping_to_more_than_one_quote_id_D22_plus_D20"] = int((gi > 1).sum())
    gi22 = pd.concat([d22[["quote_id", "isin"]].dropna(), d22[["quote_id", "new_isin"]].rename(columns={"new_isin": "isin"}).dropna()]).drop_duplicates()
    gi22 = gi22.groupby("isin")["quote_id"].nunique()
    c["isins_mapping_to_more_than_one_quote_id_D22_only"] = int((gi22 > 1).sum())
    multi = gi[gi > 1].index
    # those that matter (in D20 ranked top-250 at any time or in D21)
    top = my_rank_panel(d20)
    top250_isins = set(top.loc[top["rank"] <= 250, "isin"].dropna())
    c["multi_qid_isins_in_D20_top250_ever_or_D21"] = sorted(set(multi) & (top250_isins | set(d21["isin"])))
    c["d22_isin_changed_flag_true"] = int(d22["isin_changed_flag"].astype(str).str.lower().eq("true").sum())
    c["d22_isin_changed_with_both_isins"] = int((d22["isin_changed_flag"].astype(str).str.lower().eq("true") & d22["isin"].notna() & d22["new_isin"].notna()).sum())
    c["d22_instrument_class_counts"] = d22["instrument_class"].value_counts().to_dict()
    return c


# ----------------------------------------------------------------------------------------------
# CHECK 2
# ----------------------------------------------------------------------------------------------
def check2(d20, d21):
    c = {}
    d = d20.copy()
    d["dd"] = pd.to_datetime(d["date"])
    d["ua"] = pd.to_datetime(d["updated_at"].str[:19])
    d["lag_days"] = (d["ua"] - d["dd"]).dt.days
    d["yr"] = d["dd"].dt.year
    t = d.groupby("yr").agg(rows=("lag_days", "size"), min_lag=("lag_days", "min"), median_lag=("lag_days", "median"),
                            max_lag=("lag_days", "max"), n_distinct_updated_at_days=("ua", lambda s: s.dt.date.nunique()),
                            first_updated=("ua", "min"), last_updated=("ua", "max"))
    c["updated_at_vs_date_by_year"] = {int(k): {kk: (str(vv) if isinstance(vv, pd.Timestamp) else (float(vv) if isinstance(vv, (float, np.floating)) else int(vv)))
                                              for kk, vv in row.items()} for k, row in t.iterrows()}
    c["rows_written_after_their_date_by_more_than_7_days_by_year"] = d[d["lag_days"] > 7].groupby("yr").size().to_dict()
    c["rows_written_within_8_days_by_year"] = d[d["lag_days"] <= 8].groupby("yr").size().to_dict()
    c["backfill_batch_updated_at"] = sorted(d.loc[d["yr"] < 2026, "updated_at"].str[:19].unique())[:5]
    # 2025: which dates are inside the back-fill batch and which are live
    c["lag_by_date_2025"] = d[d["yr"] == 2025].groupby("date")["lag_days"].agg(["min", "max"]).to_dict("index")
    first_live = d[d["lag_days"] <= 8]["date"].min()
    c["first_date_written_within_8_days"] = first_live
    c["d21_inserted_at_minus_snapshot_days"] = (
        pd.to_datetime(d21["inserted_at"].str[:19]) - pd.to_datetime(d21["snapshot_date"])).dt.days.groupby(d21["snapshot_date"]).agg(["min", "max"]).to_dict("index")
    # what changes between the back-filled history and a live snapshot: ISIN-today test on back-filled rows
    # (a) the ISIN on a back-filled row vs the ISIN on the stock's latest row (quote_id based)
    last_isin = d.dropna(subset=["isin"]).sort_values("date").groupby("quote_id")["isin"].last()
    bf = d[(d["yr"] < 2026) & d["isin"].notna()]
    bf = bf.assign(last_isin=bf["quote_id"].map(last_isin))
    c["backfilled_rows_with_isin_different_from_the_quote_ids_latest_isin"] = int((bf["isin"] != bf["last_isin"]).sum())
    # (b) within a quote_id, how many have more than one ISIN over time
    g = d.dropna(subset=["isin"]).groupby("quote_id")["isin"].nunique()
    c["quote_ids_with_more_than_one_isin_over_time"] = int((g > 1).sum())
    # (c) shares: implied shares = mcap/close ; jumps within 2018-2025 month-to-month > 25% for top-250 names (information only)
    r = my_rank_panel(d20)
    d_ = d.merge(r[["date", "quote_id", "rank"]], on=["date", "quote_id"], how="left")
    d_["shares"] = d_["mcap"] / d_["close"]
    top = d_[(d_["rank"] <= 250)].sort_values(["quote_id", "date"])
    top["sh_chg"] = top.groupby("quote_id")["shares"].pct_change()
    top["gap_ok"] = top.groupby("quote_id")["dd"].diff().dt.days
    m = top[(top["yr"] < 2026) & (top["gap_ok"] <= 35)]
    c["implied_shares_monthly_change_over_25pct_top250_2018_2025"] = int((m["sh_chg"].abs() > 0.25).sum())
    c["implied_shares_monthly_change_over_25pct_by_year"] = m[m["sh_chg"].abs() > 0.25].groupby("yr").size().to_dict()
    c["top250_monthly_obs_2018_2025"] = int(len(m))
    # share-count changes between consecutive daily 2026 rows (live), for contrast
    m26 = top[(top["yr"] == 2026) & (top["gap_ok"] <= 5)]
    c["implied_shares_daily_change_over_25pct_top250_2026"] = int((m26["sh_chg"].abs() > 0.25).sum())
    c["top250_daily_obs_2026"] = int(len(m26))
    c["note_on_close"] = "mcap/close implied share count; close is as stored (unadjusted unknown); used only as a descriptive probe"
    return c


# ----------------------------------------------------------------------------------------------
def main_partA():
    d20, d21, d22 = load_raw()
    sess = load_calendar()
    R["inputs"] = {
        "D20": {"file": EXT + "mcap_universe/mcap_universe_ordinary.csv", "sha256_16": sha16(EXT + "mcap_universe/mcap_universe_ordinary.csv"), "rows": len(d20)},
        "D21": {"file": EXT + "membership/index_constituents_monthly.csv", "sha256_16": sha16(EXT + "membership/index_constituents_monthly.csv"), "rows": len(d21)},
        "D22": {"file": EXT + "symbology/symbology_changes.csv", "sha256_16": sha16(EXT + "symbology/symbology_changes.csv"), "rows": len(d22)},
        "D23_rank": {"file": EXT + "tags/mcap_rank_panel.csv", "sha256_16": sha16(EXT + "tags/mcap_rank_panel.csv")},
        "D23_membership": {"file": EXT + "tags/membership_panel.csv", "sha256_16": sha16(EXT + "tags/membership_panel.csv")},
    }
    R["check1"] = check1(d20, d21, d22, sess)
    R["check2_part"] = check2(d20, d21)
    # check 3: own rebuild, saved to scratch BEFORE the puller's code is read
    mine_r = my_rank_panel(d20)
    mine_m = my_membership_panel(d21)
    mine_r.to_csv(os.path.join(SCRATCH, "my_rank_panel.csv"), index=False)
    mine_m.to_csv(os.path.join(SCRATCH, "my_membership_panel.csv"), index=False)
    th_r = rd(EXT + "tags/mcap_rank_panel.csv")
    th_m = rd(EXT + "tags/membership_panel.csv")
    c3 = {}
    c3["rank_columns_match"] = list(th_r.columns) == ["date", "quote_id", "isin", "ticker", "mcap", "rank", "n_ranked", "band"]
    c3["membership_columns_match"] = list(th_m.columns) == ["snapshot_date", "index_name", "isin", "symbol", "band"]
    cr = compare_frames(mine_r, th_r, ["date", "quote_id"], ["isin", "ticker", "mcap", "rank", "n_ranked", "band"], "rank panel")
    cm = compare_frames(mine_m, th_m, ["snapshot_date", "index_name", "isin"], ["symbol", "band"], "membership panel")
    # the rank-panel rows in the same order as mine?
    c3["rank_panel_row_order_identical"] = bool(len(th_r) == len(mine_r) and (th_r[["date", "quote_id"]].values == mine_r[["date", "quote_id"]].values).all())
    c3["membership_panel_row_order_identical"] = bool(len(th_m) == len(mine_m) and (th_m[["snapshot_date", "isin"]].fillna("").values == mine_m[["snapshot_date", "isin"]].fillna("").values).all())
    c3["rank_mcap_max_abs_diff"] = float((mine_r.merge(th_r, on=["date", "quote_id"], suffixes=("_m", "_t")).pipe(lambda x: (x["mcap_m"] - x["mcap_t"]).abs().max())))
    c3["rank_panel"] = strip_private(cr)
    c3["membership_panel"] = strip_private(cm)
    c3["zero_differences"] = bool(cr["zero_differences"] and cm["zero_differences"])
    c3["rows_compared_total"] = cr["rows_compared"] + cm["rows_compared"]
    c3["my_rebuild_saved_to"] = SCRATCH
    c3["my_rebuild_sha256_16"] = {"rank": sha16(os.path.join(SCRATCH, "my_rank_panel.csv")), "membership": sha16(os.path.join(SCRATCH, "my_membership_panel.csv"))}
    R["check3"] = c3
    return d20, d21, d22, sess, mine_r, mine_m, th_r, th_m




# ==============================================================================================
# PART B (checks 4-9).  Written after the puller's modules were read (check 3 had been saved first).
# ==============================================================================================
sys.path.insert(0, os.path.join(AA, "analysis"))
H = "data/holdings_matrix/"
SIGNAL_BUCKET = {"Large": "Nifty 100 signal", "Mid": "Midcap 100 signal", "Small and below": "Smallcap 100 signal"}


class MyTag:
    """My own implementation of the tag rule, built from my own panels (not from D23 and not from tag_lookup.py)."""

    def __init__(self, rank, memb, d20, d22):
        pairs = pd.concat([
            d22[["quote_id", "isin"]],
            d22[["quote_id", "new_isin"]].rename(columns={"new_isin": "isin"}),
            d20[["quote_id", "isin"]],
        ]).dropna().drop_duplicates()
        self.q_of_i, self.i_of_q = {}, {}
        for q, i in sorted(zip(pairs["quote_id"].astype(int), pairs["isin"])):
            self.q_of_i.setdefault(i, []).append(q)
            self.i_of_q.setdefault(q, []).append(i)
        self.rank_dates = np.array(sorted(pd.to_datetime(rank["date"]).unique()), dtype="datetime64[ns]")
        self._rg = {pd.Timestamp(k): v for k, v in rank.assign(_d=pd.to_datetime(rank["date"])).groupby("_d")}
        self._rc = {}
        self.memb_dates = np.array(sorted(pd.to_datetime(memb["snapshot_date"]).unique()), dtype="datetime64[ns]")
        self.cutoff = pd.Timestamp(self.memb_dates[0])
        self.memb = {pd.Timestamp(k): dict(zip(v["isin"], zip(v["index_name"], v["band"])))
                     for k, v in memb.assign(_d=pd.to_datetime(memb["snapshot_date"])).groupby("_d")}
        self.ambiguous = 0

    @staticmethod
    def latest(arr, d):
        i = np.searchsorted(arr, np.datetime64(d), side="right") - 1
        return None if i < 0 else pd.Timestamp(arr[i])

    def alts(self, isin):
        out = []
        for q in self.q_of_i.get(isin, []):
            for a in self.i_of_q[q]:
                if a != isin and a not in out:
                    out.append(a)
        return out

    def snap(self, s):
        if s not in self._rc:
            g = self._rg[s]
            self._rc[s] = (dict(zip(g["quote_id"].astype(int), zip(g["rank"].astype(int), g["band"]))),
                           {i: int(q) for i, q in zip(g["isin"], g["quote_id"]) if isinstance(i, str)})
        return self._rc[s]

    def rank_hit(self, s, isin):
        by_q, by_i = self.snap(s)
        if isin in by_i:
            return by_q[by_i[isin]]
        for q in self.q_of_i.get(isin, []):
            if q in by_q:
                return by_q[q]
        return None

    def tag(self, isin, asof):
        d = pd.Timestamp(asof)
        res = {"band": "Small and below", "source": "unranked", "snapshot": None, "detail": None}
        if not isinstance(isin, str) or not isin:
            return res
        src = "rank"
        if d >= self.cutoff:
            s = self.latest(self.memb_dates, d)
            m = self.memb[s]
            if isin in m:
                return {"band": m[isin][1], "source": "membership", "snapshot": str(s.date()), "detail": m[isin][0]}
            cand = [a for a in self.alts(isin) if a in m]
            if cand:
                if len({m[a][1] for a in cand}) > 1:
                    self.ambiguous += 1
                a = cand[0]
                return {"band": m[a][1], "source": "membership", "snapshot": str(s.date()), "detail": m[a][0]}
            src = "nonmember_rank"
        s = self.latest(self.rank_dates, d)
        if s is None:
            return res
        h = self.rank_hit(s, isin)
        if h is None:
            return {**res, "snapshot": str(s.date())}
        return {"band": h[1], "source": src, "snapshot": str(s.date()), "detail": h[0]}


def load_baskets():
    """Per parent: list of non-skipped baskets (available_date, {isin: weight}, {isin: column}); checks D19 vs D05."""
    out, info = {}, {}
    for p in PARENTS:
        m = rd(H + f"SCMO_{p}_holding_weight_matrix.csv")
        m["rebalance_date"] = pd.to_datetime(m["rebalance_date"])
        src = rd(H + f"SCMO_{p}_holding_weight_sources.csv")
        src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
        cols = rd(H + f"SCMO_{p}_columns.csv")
        isin_of = dict(zip(cols["stock"], cols["ISIN"]))
        skipped = dict(zip(src["rebalance_date"], src["csv_skipped_flag"].astype(str).str.lower().eq("true")))
        d05 = rd(f"Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_{p}.csv")
        d05["ad"] = pd.to_datetime(d05["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
        d05["sk"] = d05["skipped"].astype(str).str.lower().eq("true")
        g = d05.groupby("ad")["sk"].agg(["min", "max"])
        mixed = int((g["min"] != g["max"]).sum())
        d05sk = dict(zip(g.index, g["max"]))
        agree = all(d05sk.get(d) == skipped[d] for d in m["rebalance_date"])
        same_dates = set(m["rebalance_date"]) <= set(d05sk)
        baskets = []
        for _, row in m.iterrows():
            d = row["rebalance_date"]
            if skipped[d]:
                continue
            w = {c: row[c] for c in m.columns[1:] if row[c] > 0}
            baskets.append((d, {isin_of[c]: v for c, v in w.items()}, {isin_of[c]: c for c in w}))
        out[p] = baskets
        info[p] = {"baskets_total": len(m), "baskets_skipped": int(sum(skipped.values())), "baskets_used": len(baskets),
                   "d05_skipped_flag_agrees_with_sources_file": bool(agree), "matrix_dates_all_in_d05": bool(same_dates),
                   "d05_baskets_with_mixed_skipped_flags": mixed, "first_basket": str(m["rebalance_date"].min().date()),
                   "last_basket": str(m["rebalance_date"].max().date()),
                   "columns_dup_isin": int(cols["ISIN"].duplicated().sum()), "n_columns": len(cols)}
    return out, info


def weekly_dates(sess):
    out = {}
    for p, s in sess.items():
        iso = s.dt.isocalendar()
        last = s.groupby([iso["year"], iso["week"]]).max()
        out[p] = sorted(x for x in last if x >= s.min() and x <= SIGNAL_END)
    return out


def build_population(baskets, weeks):
    rows = []
    for p in PARENTS:
        bd = np.array([np.datetime64(b[0]) for b in baskets[p]], dtype="datetime64[ns]")
        for d in weeks[p]:
            i = np.searchsorted(bd, np.datetime64(d), side="right") - 1
            if i < 0:
                continue
            bdate, w, col = baskets[p][i]
            for isin, wt in w.items():
                rows.append((p, d, bdate, isin, col[isin], wt))
    return pd.DataFrame(rows, columns=["parent", "date", "basket_date", "isin", "stock", "weight"])


def same(a, b):
    return a["band"] == b["band"] and a["source"] == b["source"] and a["snapshot"] == b["snapshot"] and str(a["detail"]) == str(b["detail"])


def jd(x):
    return json.dumps(x, default=jdefault)


def check4_5(mt, tl, pop, d20, d21, d22):
    c4, c5 = {}, {}
    tl_cache, my_cache, mism = {}, {}, []
    uniq = pop[["isin", "date"]].drop_duplicates()
    for isin, d in zip(uniq["isin"], uniq["date"]):
        a = mt.tag(isin, d)
        b = tl.tag(isin, d)
        my_cache[(isin, d)] = a
        tl_cache[(isin, d)] = b
        if not same(a, b):
            mism.append({"scope": "population", "isin": isin, "date": str(d.date()), "mine": jd(a), "puller": jd(b)})
    c4["population_holding_weeks"] = int(len(pop))
    c4["population_unique_isin_date_pairs"] = int(len(uniq))
    c4["population_mismatches"] = len(mism)
    c4["population_weekly_dates_by_parent"] = {p: int(pop.loc[pop["parent"] == p, "date"].nunique()) for p in PARENTS}
    c4["my_ambiguous_membership_alias_cases_in_population"] = int(mt.ambiguous)
    pop = pop.assign(src=[my_cache[(i, d)]["source"] for i, d in zip(pop["isin"], pop["date"])],
                     band=[my_cache[(i, d)]["band"] for i, d in zip(pop["isin"], pop["date"])],
                     via=[tl_cache[(i, d)].get("via") for i, d in zip(pop["isin"], pop["date"])])
    c4["population_source_counts_holding_weeks"] = pop["src"].value_counts().to_dict()
    c4["population_band_counts_holding_weeks"] = pop["band"].value_counts().to_dict()
    c4["population_found_via_symbology_holding_weeks"] = int((pop["via"] == "symbology").sum())
    c4["population_found_via_symbology_unique_isins"] = int(pop.loc[pop["via"] == "symbology", "isin"].nunique())

    edge_dates = ["2018-01-15", "2018-01-31", "2018-02-14", "2018-03-29", "2024-06-14", "2025-12-30", "2025-12-31", "2026-01-01",
                  "2026-02-01", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10", "2026-05-03", "2026-05-04", "2026-05-05",
                  "2026-07-31", "2026-08-01", "2026-10-30", "2026-11-01", "2026-11-11", "2026-11-12", "2027-01-01"]
    all_isins = sorted(set(d20["isin"].dropna()) | set(d21["isin"]) | set(pop["isin"]))
    edge_mism, n_edge = [], 0
    for d in edge_dates:
        for isin in all_isins:
            a, b = mt.tag(isin, d), tl.tag(isin, d)
            n_edge += 1
            if not same(a, b):
                edge_mism.append({"scope": "edge", "isin": isin, "date": d, "mine": jd(a), "puller": jd(b)})
    c4["edge_dates"] = edge_dates
    c4["edge_isins_tested_per_date"] = len(all_isins)
    c4["edge_calls"] = n_edge
    c4["edge_mismatches"] = len(edge_mism)
    spec = {}
    for name, isin in [("RELIANCE", "INE002A01018"), ("TCS", "INE467B01029")]:
        for d in ["2018-01-15", "2018-01-31", "2026-04-08", "2026-04-09", "2026-05-03", "2026-05-04"]:
            spec[f"{name} {d}"] = mt.tag(isin, d)
    c4["edge_examples_mine"] = spec
    renamed_q = d20.dropna(subset=["isin"]).groupby("quote_id")["isin"].nunique()
    ren_calls, ren_mism, ren_ex = 0, [], []
    for q in renamed_q[renamed_q > 1].index:
        sub = d20[(d20["quote_id"] == q) & d20["isin"].notna()].sort_values("date")
        chg = sub[sub["isin"] != sub["isin"].shift()]["date"].tolist()[1:]
        dts = set()
        for cd in chg:
            t = pd.Timestamp(cd)
            for k in (-31, -1, 0, 1, 31):
                dts.add(t + pd.Timedelta(days=k))
        for isin in sorted(set(sub["isin"])):
            for d in sorted(dts):
                if d > pd.Timestamp("2026-11-12"):
                    continue
                a, b = mt.tag(isin, d), tl.tag(isin, d)
                ren_calls += 1
                if not same(a, b):
                    ren_mism.append({"scope": "renamed", "isin": isin, "date": str(d.date()), "mine": jd(a), "puller": jd(b)})
        if len(ren_ex) < 3 and chg:
            first, last = sub["isin"].iloc[0], sub["isin"].iloc[-1]
            dd = chg[0]
            ren_ex.append({"quote_id": int(q), "old_isin": first, "new_isin": last, "change_date_in_D20": dd,
                           "old_isin_tag_at_change": mt.tag(first, dd), "new_isin_tag_at_change": mt.tag(last, dd)})
    c4["renamed_quote_ids"] = int((renamed_q > 1).sum())
    c4["renamed_isin_calls"] = ren_calls
    c4["renamed_mismatches"] = len(ren_mism)
    c4["renamed_examples"] = ren_ex
    sweep_dates = [str(x.date()) for x in pd.to_datetime(sorted(d20["date"].unique()))[::5]] + ["2026-04-08", "2026-04-09"]
    sw_mism, n_sw = [], 0
    for d in sweep_dates:
        for isin in all_isins:
            a, b = mt.tag(isin, d), tl.tag(isin, d)
            n_sw += 1
            if not same(a, b):
                sw_mism.append({"scope": "sweep", "isin": isin, "date": d, "mine": jd(a), "puller": jd(b)})
    c4["sweep_dates"] = len(sweep_dates)
    c4["sweep_calls"] = n_sw
    c4["sweep_mismatches"] = len(sw_mism)
    c4["population_tags_using_snapshot_later_than_asof"] = int(sum(
        1 for (isin, d), a in my_cache.items() if a["snapshot"] is not None and pd.Timestamp(a["snapshot"]) > d))
    allm = mism + edge_mism + ren_mism + sw_mism
    c4["total_calls_compared"] = len(uniq) + n_edge + ren_calls + n_sw
    c4["total_mismatches"] = len(allm)
    c4["zero_mismatches"] = len(allm) == 0
    if allm:
        pd.DataFrame(allm).to_csv(OUT + "mismatches_check4.csv", index=False)
    elif os.path.exists(OUT + "mismatches_check4.csv"):
        os.remove(OUT + "mismatches_check4.csv")

    # ---------------- check 5: coverage
    tot = pop["weight"].sum()
    c5["weight_sum_all_holding_weeks"] = float(tot)
    c5["coverage_overall_weight_weighted"] = float(pop.loc[pop["src"] != "unranked", "weight"].sum() / tot)
    c5["coverage_overall_count_weighted"] = float((pop["src"] != "unranked").mean())
    per = {}
    for p in PARENTS:
        sp = pop[pop["parent"] == p]
        per[p] = {"coverage_weight_weighted": float(sp.loc[sp["src"] != "unranked", "weight"].sum() / sp["weight"].sum()),
                  "holding_weeks": int(len(sp)), "unranked_holding_weeks": int((sp["src"] == "unranked").sum()),
                  "weekly_dates": int(sp["date"].nunique())}
    c5["per_parent"] = per
    sy = pop[pop["via"] == "symbology"]
    c5["holding_weeks_found_only_through_symbology"] = int(len(sy))
    c5["weight_share_found_only_through_symbology"] = float(sy["weight"].sum() / tot)
    c5["coverage_if_d22_were_not_used_weight_weighted"] = float(1 - sy["weight"].sum() / tot)
    c5["symbology_names"] = sy.groupby(["parent", "isin", "stock"]).size().reset_index(name="weeks").to_dict("records")
    un = pop[pop["src"] == "unranked"]
    if len(un):
        lst = (un.groupby(["parent", "isin", "stock"]).agg(weeks=("date", "nunique"), first=("date", "min"), last=("date", "max"),
                                                           mean_weight=("weight", "mean"), max_weight=("weight", "max"),
                                                           weight_sum=("weight", "sum")).reset_index().sort_values("weight_sum", ascending=False))
        lst["first"] = lst["first"].dt.strftime("%Y-%m-%d")
        lst["last"] = lst["last"].dt.strftime("%Y-%m-%d")
        c5["unranked_names"] = lst.to_dict("records")
        why = []
        for r in lst.itertuples():
            qs = mt.q_of_i.get(r.isin, [])
            dd = d20.loc[(d20["isin"] == r.isin) | d20["quote_id"].isin(qs), "date"]
            why.append({"parent": r.parent, "isin": r.isin, "stock": r.stock, "isin_in_D20": bool((d20["isin"] == r.isin).any()),
                        "isin_in_D22_or_D20_pairs": bool(r.isin in mt.q_of_i), "quote_ids": qs,
                        "D20_first": dd.min() if len(dd) else None, "D20_last": dd.max() if len(dd) else None, "unranked_weeks": int(r.weeks)})
        c5["unranked_reasons"] = why
        c5["unranked_weeks_by_year"] = un.groupby(un["date"].dt.year)["weight"].agg(["size", "sum"]).rename(columns={"size": "holding_weeks", "sum": "weight_sum"}).to_dict("index")
    else:
        c5["unranked_names"] = []
    c5["unranked_unique_isins"] = int(un["isin"].nunique())
    c5["unranked_holding_weeks"] = int(len(un))
    c5["unranked_holding_over_2pct_weight"] = un[un["weight"] > 0.02][["parent", "date", "isin", "stock", "weight"]].assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records")
    c5["thresholds"] = {"pass_overall": 0.99, "pass_per_parent": 0.98, "notes_floor": 0.97, "fail_if_any_single_holding_over_2pct_unranked": True}
    ov = c5["coverage_overall_weight_weighted"]
    pmin = min(v["coverage_weight_weighted"] for v in per.values())
    over2 = len(c5["unranked_holding_over_2pct_weight"]) > 0
    c5["verdict"] = "FAIL" if (over2 or ov < 0.97) else ("PASS" if (ov >= 0.99 and pmin >= 0.98) else "PASS WITH NOTES")
    c5["min_parent_coverage"] = pmin
    return c4, c5, pop, my_cache


def member_lookup(mt, isin, mem_isin):
    """Real index of a holding's ISIN on a snapshot: by ISIN, else by an alias sharing its quote_id."""
    if isin in mem_isin:
        return isin
    alt = [a for a in mt.alts(isin) if a in mem_isin]
    return alt[0] if alt else None


def check6(mt, mine_r, d21, baskets):
    c = {}
    snaps = sorted(d21["snapshot_date"].unique())
    rows, allrows = [], []
    for s in snaps:
        d = mt.latest(mt.rank_dates, pd.Timestamp(s))
        g = mine_r[mine_r["date"] == str(d.date())]
        by_q = dict(zip(g["quote_id"].astype(int), zip(g["rank"], g["band"])))
        by_i = {i: int(q) for i, q in zip(g["isin"], g["quote_id"]) if isinstance(i, str)}
        mem = d21[d21["snapshot_date"] == s]
        used_q = {}
        for isin, ix in zip(mem["isin"], mem["index_name"]):
            q, via = None, None
            if isin in by_i:
                q, via = by_i[isin], "isin"
            else:
                for qq in mt.q_of_i.get(isin, []):
                    if qq in by_q:
                        q, via = qq, "symbology"
                        break
            if q is None:
                pred, rk, unr = "Small and below", None, True
            else:
                rk, pred = by_q[q]
                unr = False
                used_q[q] = ix
            rows.append({"snapshot": s, "isin": isin, "index": ix, "real": INDEX_BAND[ix], "pred": pred, "rank": rk,
                         "unranked": unr, "via": via, "d20_date": str(d.date())})
        for q, (rk, b) in by_q.items():
            allrows.append((s, q, rk, b, used_q.get(q)))
    m = pd.DataFrame(rows)
    m["ok"] = m["real"] == m["pred"]
    c["members_pooled"] = int(len(m))
    c["agreement_pooled"] = float(m["ok"].mean())
    per = m.groupby("snapshot")["ok"].agg(["mean", "size"])
    c["agreement_per_snapshot"] = {k: {"agreement": float(v["mean"]), "members": int(v["size"])} for k, v in per.iterrows()}
    c["agreement_mean_of_snapshots"] = float(per["mean"].mean())
    c["members_unranked_pooled"] = int(m["unranked"].sum())
    c["members_unranked_by_snapshot"] = {k: int(v) for k, v in m.groupby("snapshot")["unranked"].sum().items()}
    c["members_found_via_symbology"] = int((m["via"] == "symbology").sum())
    c["agreement_pooled_excluding_unranked"] = float(m.loc[~m["unranked"], "ok"].mean())
    conf = pd.crosstab(m["real"], m["pred"]).reindex(index=BANDS, columns=BANDS, fill_value=0)
    c["confusion_real_rows_by_predicted_cols"] = conf.to_dict("index")
    c["recall_per_band"] = {b: float(conf.loc[b, b] / conf.loc[b].sum()) for b in BANDS}
    c["real_members_per_band_pooled"] = {k: int(v) for k, v in conf.sum(axis=1).items()}
    c["recall_by_index"] = {ix: float(m.loc[m["index"] == ix, "ok"].mean()) for ix in INDEX_BAND}
    c["pred_band_by_index"] = pd.crosstab(m["index"], m["pred"]).reindex(columns=BANDS, fill_value=0).to_dict("index")
    a = pd.DataFrame(allrows, columns=["snapshot", "quote_id", "rank", "pred", "index"])
    a["real"] = a["index"].map(INDEX_BAND).fillna("outside")
    pc = pd.crosstab(a["pred"], a["real"]).reindex(index=BANDS, columns=BANDS + ["outside"], fill_value=0)
    c["all_ranked_shares_pooled_rows"] = int(len(a))
    c["rank_called_vs_real_all_ranked_shares"] = pc.to_dict("index")
    c["precision_per_band_share_of_rank_called_band_that_are_real_members_of_it"] = {b: float(pc.loc[b, b] / pc.loc[b].sum()) for b in BANDS}
    c["ranked_nonmembers_called_Large_pooled"] = int(pc.loc["Large", "outside"])
    c["ranked_nonmembers_called_Mid_pooled"] = int(pc.loc["Mid", "outside"])
    c["ranked_nonmembers_called_Large_by_snapshot"] = {k: int(v) for k, v in a[(a["pred"] == "Large") & (a["real"] == "outside")].groupby("snapshot").size().items()}
    c["ranked_nonmembers_called_Mid_by_snapshot"] = {k: int(v) for k, v in a[(a["pred"] == "Mid") & (a["real"] == "outside")].groupby("snapshot").size().items()}
    c["ranked_nonmembers_called_Small_pooled"] = int(pc.loc["Small and below", "outside"])
    c["note_precision_small"] = "Small and below holds every ranked share below 250, most in no index, so its precision against index membership is not meaningful."
    # parents' holdings at the snapshots
    ph = []
    for p in PARENTS:
        bd = np.array([np.datetime64(b[0]) for b in baskets[p]], dtype="datetime64[ns]")
        for s in snaps:
            i = np.searchsorted(bd, np.datetime64(pd.Timestamp(s)), side="right") - 1
            for isin, w in baskets[p][i][1].items():
                ph.append((p, s, isin, w))
    ph = pd.DataFrame(ph, columns=["parent", "snapshot", "isin", "weight"])
    mrow = m.set_index(["snapshot", "isin"])
    mem_by = {s: dict(zip(g["isin"], g["index_name"])) for s, g in d21.groupby("snapshot_date")}
    real, pred = [], []
    for p_, s, isin, w in ph.itertuples(index=False):
        key = member_lookup(mt, isin, mem_by[s])
        if key is None:
            real.append(None); pred.append(None)
        else:
            real.append(INDEX_BAND[mem_by[s][key]]); pred.append(mrow.loc[(s, key), "pred"])
    ph["real"], ph["pred"] = real, pred
    ph["member"] = ph["real"].notna()
    ph["ok"] = ph["real"] == ph["pred"]
    pm = ph[ph["member"]]
    c["parents_holdings_at_snapshots"] = {
        "holding_obs": int(len(ph)), "member_obs": int(len(pm)), "nonmember_obs": int((~ph["member"]).sum()),
        "weight_total": float(ph["weight"].sum()), "weight_in_members": float(pm["weight"].sum()),
        "weight_not_in_any_index": float(ph.loc[~ph["member"], "weight"].sum()),
        "agreement_weight_weighted_among_members": float((pm["ok"] * pm["weight"]).sum() / pm["weight"].sum()),
        "agreement_count_among_members": float(pm["ok"].mean()),
        "per_parent_weight_weighted": {p: float((g["ok"] * g["weight"]).sum() / g["weight"].sum()) for p, g in pm.groupby("parent")},
        "per_real_band_weight_weighted_recall": {b: float((g["ok"] * g["weight"]).sum() / g["weight"].sum()) for b, g in pm.groupby("real")},
        "weight_by_real_band": {k: float(v) for k, v in pm.groupby("real")["weight"].sum().items()},
        "confusion_weight": pd.crosstab(pm["real"], pm["pred"], values=pm["weight"], aggfunc="sum").fillna(0).reindex(index=BANDS, columns=BANDS, fill_value=0).to_dict("index"),
    }
    prim = c["agreement_pooled"]
    c["primary_figure_pooled_agreement"] = prim
    c["thresholds"] = {"pass": 0.90, "notes": 0.85}
    c["verdict"] = "PASS" if prim >= 0.90 else ("PASS WITH NOTES" if prim >= 0.85 else "FAIL")
    c["regime_caveat"] = "All 8 D21 snapshots are in 2026-04 to 2026-11, one regime; nothing here tests the rank-based tags before 2026-04."
    m.to_csv(OUT + "check6_member_predictions.csv", index=False)
    return c


def check7(mine_r, mt, d20, d21):
    c = {}
    r = mine_r.copy()
    r["dt"] = pd.to_datetime(r["date"])
    r["ym"] = r["dt"].dt.year * 12 + r["dt"].dt.month
    last = r.groupby("ym")["dt"].max()
    me = r[r["dt"].isin(set(last))].copy()
    ordn = {"Large": 0, "Mid": 1, "Small and below": 2}
    me["b"] = me["band"].map(ordn)
    me = me.sort_values(["quote_id", "dt"])
    for col in ["b", "rank", "dt", "ym"]:
        me["prev_" + col] = me.groupby("quote_id")[col].shift()
    me = me[(me["ym"] - me["prev_ym"]) == 1].copy()
    me["bjump"] = (me["b"] - me["prev_b"]).abs()
    me["rjump"] = me["rank"] - me["prev_rank"]
    c["month_end_pairs_compared"] = int(len(me))
    c["month_end_snapshots"] = int(len(last))
    c["note"] = ("With three bands the largest possible one-month band move is two bands (Large <-> Small and below), so 'more than two bands' cannot occur. "
                 "Reported: exactly-two-band moves per year, and the 20 largest rank moves among stocks inside the top 250 at either end.")
    two = me[me["bjump"] == 2]
    c["two_band_moves_by_year"] = {int(k): int(v) for k, v in two.groupby(two["dt"].dt.year).size().items()}
    c["two_band_moves_total"] = int(len(two))
    c["one_band_moves_total"] = int((me["bjump"] == 1).sum())
    c["pairs_by_year"] = {int(k): int(v) for k, v in me.groupby(me["dt"].dt.year).size().items()}
    top = me[(me["rank"] <= 250) | (me["prev_rank"] <= 250)].copy()
    top["abs"] = top["rjump"].abs()
    top = top.sort_values("abs", ascending=False).head(20)
    c["largest_20_rank_moves_top250"] = [{"quote_id": int(x.quote_id), "ticker": x.ticker, "isin": x.isin, "from_date": str(x.prev_dt.date()),
                                          "to_date": str(x.dt.date()), "from_rank": int(x.prev_rank), "to_rank": int(x.rank)} for x in top.itertuples()]
    c["two_band_move_examples"] = [{"ticker": x.ticker, "isin": x.isin, "from_date": str(x.prev_dt.date()), "to_date": str(x.dt.date()),
                                    "from_rank": int(x.prev_rank), "to_rank": int(x.rank)}
                                   for x in two.assign(a=two["rjump"].abs()).sort_values("a", ascending=False).head(10).itertuples()]
    snaps = sorted(d21["snapshot_date"].unique())
    a_latest, a_any, detail = {}, {}, {}
    all_isin = set(d20["isin"].dropna())
    for s in snaps:
        d = mt.latest(mt.rank_dates, pd.Timestamp(s))
        g = mine_r[mine_r["date"] == str(d.date())]
        have, have_q = set(g["isin"].dropna()), set(g["quote_id"].astype(int))
        mem = d21[d21["snapshot_date"] == s]
        absent = [i for i in mem["isin"] if i not in have]
        a_latest[s] = len(absent)
        a_any[s] = int((~mem["isin"].isin(all_isin)).sum())
        res = []
        for i in absent:
            hit = [q for q in mt.q_of_i.get(i, []) if q in have_q]
            res.append({"isin": i, "symbol": mem.loc[mem["isin"] == i, "symbol"].iloc[0], "resolved_by_D22": bool(hit),
                        "isin_on_D20_snapshot": [g.loc[g["quote_id"] == q, "isin"].iloc[0] for q in hit] if hit else None})
        if res:
            detail[s] = res
    c["d21_members_absent_from_d20_by_isin_latest_d20_on_or_before_snapshot"] = a_latest
    c["d21_members_absent_by_isin_from_all_of_d20"] = a_any
    c["d21_absent_detail"] = detail
    c["d21_absent_total"] = int(sum(a_latest.values()))
    c["d21_absent_resolved_by_d22_total"] = int(sum(1 for x in detail.values() for y in x if y["resolved_by_D22"]))
    return c


def check7b(mine_r, d20, pop, my_cache, mt):
    """Isolated implied-share-count blips (mcap/close jumps away and comes back): a data-quality probe on D20, not a gate."""
    c = {}
    x = mine_r.merge(d20[["date", "quote_id", "close"]], on=["date", "quote_id"])
    x["sh"] = x["mcap"] / x["close"]
    x["dt"] = pd.to_datetime(x["date"])
    x = x.sort_values(["quote_id", "dt"]).reset_index(drop=True)
    g = x.groupby("quote_id")
    x["r_prev"] = x["sh"] / g["sh"].shift(1)
    x["r_next"] = g["sh"].shift(-1) / x["sh"]
    x["gap_prev"] = (x["dt"] - g["dt"].shift(1)).dt.days
    x["gap_next"] = (g["dt"].shift(-1) - x["dt"]).dt.days
    x["rank_prev"] = g["rank"].shift(1)
    x["band_prev"] = g["band"].shift(1)
    x["rank_next"] = g["rank"].shift(-1)
    ok = (x["gap_prev"] <= 35) & (x["gap_next"] <= 35)
    up = (x["r_prev"] > 1.25) & (x["r_next"] < 0.8)
    dn = (x["r_prev"] < 0.8) & (x["r_next"] > 1.25)
    x["blip"] = ok & (up | dn)
    near = (x["rank"] <= 300) | (x["rank_prev"] <= 300) | (x["rank_next"] <= 300)
    b = x[x["blip"] & near]
    c["definition"] = "implied shares = mcap/close; a blip = shares move by more than 25% against both neighbours (consecutive snapshots at most 35 days apart) in opposite directions, i.e. jump away and come back; rank within 300 on the snapshot or a neighbour"
    c["blips_top300_total"] = int(len(b))
    c["blips_top300_by_year"] = {int(k): int(v) for k, v in b.groupby(b["dt"].dt.year).size().items()}
    c["blips_top300_that_move_rank_across_a_band_edge"] = int((b["band"] != b["band_prev"]).sum())
    c["blip_examples"] = [{"ticker": r.ticker, "date": r.date, "rank_prev": int(r.rank_prev), "rank": int(r.rank), "rank_next": int(r.rank_next),
                           "implied_shares_m": round(r.sh / 1e6, 1)} for r in b.reindex(b["rank"].sub(b["rank_prev"]).abs().sort_values(ascending=False).index).head(12).itertuples()]
    key = {(r.date, r.quote_id): (r.blip, r.band_prev, r.rank_prev) for r in x.itertuples()}
    hits = []
    for (isin, d), a in my_cache.items():
        if a["source"] in ("rank", "nonmember_rank") and a["snapshot"]:
            by_q, by_i = mt.snap(pd.Timestamp(a["snapshot"]))
            q = by_i.get(isin) or next((q for q in mt.q_of_i.get(isin, []) if q in by_q), None)
            if q is None:
                continue
            k = key.get((a["snapshot"], q))
            if k and k[0] and k[1] is not None and k[1] != a["band"]:
                hits.append((isin, d, a["snapshot"], a["band"], k[1], a["detail"], k[2]))
    hs = pd.DataFrame(hits, columns=["isin", "date", "snapshot", "band_used", "band_prev_snapshot", "rank_used", "rank_prev_snapshot"])
    if len(hs):
        pw = pop.merge(hs, on=["isin", "date"])
        c["population_holding_weeks_tagged_from_a_blip_snapshot_that_changes_the_band"] = int(len(pw))
        c["population_weight_of_those_weeks"] = float(pw["weight"].sum())
        c["population_share_of_total_weight"] = float(pw["weight"].sum() / pop["weight"].sum())
        c["population_examples"] = pw.sort_values("weight", ascending=False).head(10).assign(date=lambda z: z["date"].dt.strftime("%Y-%m-%d"))[["parent", "date", "stock", "weight", "snapshot", "band_used", "rank_used", "band_prev_snapshot", "rank_prev_snapshot"]].to_dict("records")
    else:
        c["population_holding_weeks_tagged_from_a_blip_snapshot_that_changes_the_band"] = 0
    return c


def check8(mt, tl, pop, my_cache, d20, mine_r, d21):
    rng = np.random.default_rng(7)
    targets = ["2019-09-27", "2021-11-26", "2023-06-30", "2025-03-28", "2026-02-27", "2026-05-29", "2026-10-30"]
    out = []
    for p in PARENTS:
        sub = pop[pop["parent"] == p]
        dts = sorted(sub["date"].unique())
        for t in targets:
            d = min(dts, key=lambda x: abs((x - pd.Timestamp(t)).days))
            g = sub[sub["date"] == d].sort_values("isin")
            pk = g.iloc[int(rng.integers(len(g)))]
            a, b = my_cache[(pk["isin"], d)], tl.tag(pk["isin"], d)
            snap = a["snapshot"]
            raw_mcap = ntot = entry = None
            if a["source"] in ("rank", "nonmember_rank") and snap:
                by_q, by_i = mt.snap(pd.Timestamp(snap))
                q = by_i.get(pk["isin"]) or next((q for q in mt.q_of_i.get(pk["isin"], []) if q in by_q), None)
                if q is not None:
                    gg = mine_r[mine_r["date"] == snap]
                    row = gg[gg["quote_id"] == q].iloc[0]
                    raw_mcap, ntot = row["mcap"], int(row["n_ranked"])
            elif a["source"] == "membership":
                m_ = d21[d21["snapshot_date"] == snap]
                key = member_lookup(mt, pk["isin"], set(m_["isin"]))
                h = m_[m_["isin"] == key].iloc[0]
                entry = f'{h["index_name"]} ({h["symbol"]})'
            out.append({"parent": f"SCMO_{p}", "date": str(d.date()), "isin": pk["isin"], "stock": pk["stock"], "weight": pk["weight"],
                        "source": a["source"], "snapshot_used": snap, "raw_mcap": raw_mcap,
                        "rank": a["detail"] if a["source"] in ("rank", "nonmember_rank") else None, "n_ranked": ntot,
                        "membership_entry": entry, "band": a["band"], "signal_bucket": SIGNAL_BUCKET[a["band"]],
                        "puller_band": b["band"], "puller_source": b["source"], "agrees_with_puller": same(a, b)})
    t = pd.DataFrame(out)
    t.to_csv(OUT + "trace_table.csv", index=False)
    c = {"rows": len(t), "pre_cutoff_rows": int((t["date"] < "2026-04-09").sum()), "post_cutoff_rows": int((t["date"] >= "2026-04-09").sum()),
         "all_agree_with_puller": bool(t["agrees_with_puller"].all()), "sources": {k: int(v) for k, v in t["source"].value_counts().items()},
         "signal_bucket_assumption": "signal_bucket = the index signal that governs the band: Large -> Nifty 100, Mid -> Midcap 100, Small and below -> Smallcap 100 (my reading of the spec; PLAN_v2 not read)"}
    names = ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ICICIBANK", "ITC", "SBIN", "LT", "BHARTIARTL", "HINDUNILVR"]
    r = mine_r
    month_ends = set(r.groupby(r["date"].str[:7])["date"].max())
    hc = {}
    for n in names:
        q = d20[d20["ticker"] == n]["quote_id"].value_counts()
        if len(q) == 0:
            hc[n] = "ticker not found"
            continue
        s = r[r["quote_id"] == int(q.index[0])]
        me_ = s[s["date"].isin(month_ends)]
        hc[n] = {"quote_id": int(q.index[0]), "isin_latest": s["isin"].dropna().iloc[-1], "dates_ranked": int(len(s)),
                 "month_ends_checked": int(len(me_)), "best_rank_month_ends": int(me_["rank"].min()), "worst_rank_month_ends": int(me_["rank"].max()),
                 "month_ends_outside_top100": int((me_["rank"] > 100).sum()), "all_dates_outside_top100": int((s["rank"] > 100).sum()),
                 "worst_rank_any_date": int(s["rank"].max()),
                 "sample_ranks": {dd: (int(s.loc[s["date"] == dd, "rank"].iloc[0]) if (s["date"] == dd).any() else None)
                                  for dd in ["2018-01-31", "2019-12-31", "2021-06-30", "2023-03-31", "2025-06-30", "2026-04-08", "2026-10-30"]}}
    c["large_cap_hand_check"] = hc
    return c


def check9(mine_r, mine_m, th_r, th_m, tl_cls, pop, my_cache):
    """Corrupt copies of D23's rank panel in scratch; checks 3 and 4 must flag each corruption."""
    c = {}
    sn = {}
    for (isin, d), a in my_cache.items():
        if a["source"] in ("rank", "nonmember_rank") and a["snapshot"]:
            sn.setdefault(a["snapshot"], set()).add(isin)
    pre = th_r[th_r["date"].isin(list(sn))]
    keep = pre[[r_ in sn[d] for r_, d in zip(pre["isin"], pre["date"])]]
    keep = keep[keep["rank"] <= 400]
    rng = np.random.default_rng(11)
    idx = list(keep.index[rng.permutation(len(keep))])[:300]
    out = {}
    uniq = pop[["isin", "date"]].drop_duplicates()
    for k in ["shift_ranks", "flip_bands", "delete_rows", "change_quote_id", "change_isin", "tiny_mcap_edit"]:
        t = th_r.copy()
        if k == "shift_ranks":
            t.loc[idx, "rank"] = t.loc[idx, "rank"] + 60
        elif k == "flip_bands":
            t.loc[idx, "band"] = t.loc[idx, "band"].map({"Large": "Small and below", "Mid": "Large", "Small and below": "Mid"})
        elif k == "delete_rows":
            t = t.drop(index=idx)
        elif k == "change_quote_id":
            t.loc[idx, "quote_id"] = t.loc[idx, "quote_id"] + 1
        elif k == "change_isin":
            t.loc[idx, "isin"] = "INE000000000"
        else:
            t.loc[idx[:3], "mcap"] = t.loc[idx[:3], "mcap"] * 1.0000001
        p_ = os.path.join(SCRATCH, f"corrupt_{k}.csv")
        t.to_csv(p_, index=False)
        cr = compare_frames(mine_r, rd(p_), ["date", "quote_id"], ["isin", "ticker", "mcap", "rank", "n_ranked", "band"], k)
        tl = tl_cls.from_files(p_, EXT + "tags/membership_panel.csv", EXT + "symbology/symbology_changes.csv")
        n_bad = sum(1 for isin, d in zip(uniq["isin"], uniq["date"]) if not same(my_cache[(isin, d)], tl.tag(isin, d)))
        out[k] = {"rows_touched": 3 if k == "tiny_mcap_edit" else len(idx), "check3_flags_it": not cr["zero_differences"],
                  "check3_rows_with_diff": cr["rows_with_any_diff"], "check3_only_in_mine": cr["only_in_mine"],
                  "check3_only_in_theirs": cr["only_in_theirs"], "check4_population_mismatches": n_bad, "check4_flags_it": n_bad > 0}
    # membership corruption: flip the band of 5 members that the parents' holdings are actually tagged from
    hit = [(a["snapshot"], isin) for (isin, d), a in my_cache.items() if a["source"] == "membership"]
    hit = sorted(set(hit))[:5]
    tm = th_m.copy()
    for sd, isin in hit:
        mk = (tm["snapshot_date"] == sd) & (tm["isin"] == isin)
        tm.loc[mk, "band"] = tm.loc[mk, "band"].map({"Large": "Small and below", "Mid": "Large", "Small and below": "Large"})
    pm = os.path.join(SCRATCH, "corrupt_membership.csv")
    tm.to_csv(pm, index=False)
    cm = compare_frames(mine_m, rd(pm), ["snapshot_date", "index_name", "isin"], ["symbol", "band"], "membership flip")
    tl = tl_cls.from_files(EXT + "tags/mcap_rank_panel.csv", pm, EXT + "symbology/symbology_changes.csv")
    n_bad = sum(1 for isin, d in zip(uniq["isin"], uniq["date"]) if not same(my_cache[(isin, d)], tl.tag(isin, d)))
    out["membership_band_flip"] = {"rows_touched": len(hit), "check3_flags_it": not cm["zero_differences"], "check3_rows_with_diff": cm["rows_with_any_diff"],
                                   "check4_population_mismatches": n_bad, "check4_flags_it": n_bad > 0}
    c["corruptions"] = out
    c["all_flagged_by_check3"] = all(v["check3_flags_it"] for v in out.values())
    c["tag_changing_rank_corruptions_flagged_by_check4"] = all(out[k]["check4_flags_it"] for k in ["shift_ranks", "flip_bands", "delete_rows", "change_quote_id"]) and out["membership_band_flip"]["check4_flags_it"]
    c["note"] = ("tiny_mcap_edit (3 mcap values) and change_isin (300 ISIN cells) change no tag: check 3 must flag them, check 4 should not, because the lookup "
                 "recovers a stock whose ISIN is missing on a snapshot through its quote_id and D22 (by design). change_quote_id breaks identity and is flagged by both.")
    c["pass"] = bool(c["all_flagged_by_check3"] and c["tag_changing_rank_corruptions_flagged_by_check4"])
    return c


def main():
    d20, d21, d22, sess, mine_r, mine_m, th_r, th_m = main_partA()
    from tag_lookup import TagLookup  # the puller's module, opened only after check 3 was saved
    tl = TagLookup.from_files(EXT + "tags/mcap_rank_panel.csv", EXT + "tags/membership_panel.csv", EXT + "symbology/symbology_changes.csv")
    mt = MyTag(mine_r, mine_m, d20, d22)
    baskets, binfo = load_baskets()
    weeks = weekly_dates(sess)
    pop = build_population(baskets, weeks)
    R["population"] = {"baskets": binfo, "weekly_dates": {p: {"n": len(weeks[p]), "first": str(weeks[p][0].date()), "last": str(weeks[p][-1].date())} for p in PARENTS},
                       "holding_weeks": int(len(pop)), "unique_isins": int(pop["isin"].nunique()),
                       "pre_cutoff_weeks_share": float((pop["date"] < "2026-04-09").mean())}
    R["check4"], R["check5"], pop2, my_cache = check4_5(mt, tl, pop, d20, d21, d22)
    R["check6"] = check6(mt, mine_r, d21, baskets)
    R["check7"] = check7(mine_r, mt, d20, d21)
    R["check7"]["share_count_blips"] = check7b(mine_r, d20, pop2, my_cache, mt)
    R["check8"] = check8(mt, tl, pop2, my_cache, d20, mine_r, d21)
    R["check9"] = check9(mine_r, mine_m, th_r, th_m, TagLookup, pop2, my_cache)
    R["check2"] = R.pop("check2_part")
    gates = bool(R["check3"]["zero_differences"] and R["check4"]["zero_mismatches"])
    v5, v6 = R["check5"]["verdict"], R["check6"]["verdict"]
    if (not gates) or v5 == "FAIL" or v6 == "FAIL" or not R["check9"]["pass"]:
        verdict = "FAIL"
    else:
        verdict = "PASS WITH NOTES"
    R["verdict_machine"] = {"hard_gates_zero": gates, "check5": v5, "check6": v6, "check9_pass": R["check9"]["pass"], "verdict": verdict,
                            "note": "PASS WITH NOTES is the best this script assigns: check 2 (back-filled history) and check 6 (one regime) always carry caveats the page must disclose; REVIEW.md carries the reasoning and Manu decides."}
    with open(OUT + "results.json", "w") as f:
        json.dump(R, f, indent=1, default=jdefault)
    return R


if __name__ == "__main__":
    main()
    print("wrote", OUT + "results.json")
